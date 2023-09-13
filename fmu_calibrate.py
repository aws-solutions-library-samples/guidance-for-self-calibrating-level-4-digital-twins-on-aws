# -*- coding: utf-8 -*-
"""
Created on Mon May 15 10:53:20 2023

@author: rpivovar

"""


#generic packages
import sys
import pandas
from functools import reduce
import numpy as np
import matplotlib.pyplot as plot
import random
import copy
from tqdm import tqdm
from datetime import datetime
sys.path.append('/wd')


#twinmodule packages
from twinmodules.core.components import run_fmu
from twinmodules.core.util import get_user_json_config, get_cloudformation_metadata
from twinmodules.AWSModules.AWS_sitewise import get_asset_property_data
from twinmodules.AWSModules.AWS_S3 import send_data_s3, s3_object_exist, get_data_s3
from twinmodules.AWSModules.AWS_sitewise import send_asset_property_data

#twinstat packages
from twinstat.statespace_models.estimators import kalman


#global variables
ukf_savepoint = 'ukf_savepoint.npz'


def get_data(config, metadata):
    sitewise_names = [value for key, value in config.items() if 'measured' in key]
    assetId = metadata['MyCfnAsset']

    sitewise_data = []
    for name in sitewise_names:
        tmp = get_asset_property_data(  name,
                                        assetId,
                                        maxResults=15
                                        )
        tmp.columns = [x  if 'time' in x else name  for x in tmp.columns]
        sitewise_data.append(tmp)

    #merge all streams into one dataframe
    dfsw = reduce(lambda  left,right: pandas.merge(left,right,on=['time'],
                                            how='outer'), sitewise_data)
    dfsw = dfsw.dropna()
    return dfsw



class my_transition_function(object):
    def __init__(self, config:dict,
                 measured: list,
                 n_inputs:int,
                 extra_inferred:list[str]=None,
                 run_local:bool = False):
        self.config = config
        self.run_local = run_local
        self.measured = measured
        self.n_inputs = n_inputs
        self.n_measured = len(measured)
        self.extra_inferred = extra_inferred

    def run_fmu(self,X:np.array) -> np.array:

        local_config = copy.deepcopy(self.config)
        local_config['uid'] = random.getrandbits(24)

        #last 9 are the inferred damping
        damping_coefficients = X[self.n_measured:self.n_measured+self.n_inputs]
        #negative is non-physical
        damping_coefficients = np.clip(damping_coefficients, 0,0.5)
        #evaluate the digital twin
        df = run_fmu(damping_coefficients, local_config,'dummy', 0, use_cloud=False)

        #return the next state space vector in which the first group are the
        #digital twin predicted slip velocities and the last group are the xt-1
        #damping coefficients.
        predicted_slip_velocities = np.squeeze(df[self.measured].to_numpy())

        scaling = [1.0e3 if 'Tension' in col else 1 for col in self.measured ]
        predicted_slip_velocities = np.divide(predicted_slip_velocities,scaling)

        #the damping coefficients do not change based on the physics model
        damping_coefficients =  X[self.n_measured:self.n_measured+self.n_inputs]
        if self.extra_inferred is not None:
            predicted_tensions = np.squeeze(df[self.extra_inferred].to_numpy())
            Xt = np.concatenate((predicted_slip_velocities, damping_coefficients, predicted_tensions))
        else:
            Xt = np.concatenate((predicted_slip_velocities, damping_coefficients))
        return Xt

#------------------------------------------------------------------------------------------

def calibrate(dfsw, config, metadata):


    s3_bucket = [value for key, value in metadata.items() if 'datalake' in key][0]

    #check if any ukf savepoints exist
    calibrated_mean = []
    calibrated_var = []

    #TODO: add json inputs for measured, inferred, extra vars etc
    #config['eval_table'] = config['table_name']
    measured = [config[x] for x in config.keys() if 'measured' in x]

    measure_cols = measured

    # for col in measured:
    #     #col = measured[0]
    #     if 'Roller' in col:
    #         num = col.split('_')[0]
    #         num = num.replace('Roller','')
    #         match = [j for j, x in enumerate(dfsw.columns) if "Main.R{}.w".format(num) in x]
    #         measure_cols.append(match[0])
    #     elif 'deg' in col:
    #         match = [j for j, x in enumerate(dfsw.columns) if 'Dancer' in x]
    #         measure_cols.append(match[0])
    #     else:
    #         match = [j for j, x in enumerate(dfsw.columns) if '.'+col.split('_')[0]+'.' in x]
    #         measure_cols.append(match[0])


    #TODO: do a run with cov calc on all variables despite long runtimes
    # extra_inferred = [config[x] for x in config.keys() if 'SlipVelocity' in str(config[x])]
    # extra_inferred = list(set(extra_inferred))
    # import re
    # extra_inferred = sorted(extra_inferred, key=lambda s: int(re.search(r'\d+', s).group()))
    extra_inferred = None

    n_damping = 9
    n_measured = len(measured)
    n_extra = len(extra_inferred) if isinstance(extra_inferred, list) else 0

    total_vars = n_measured + n_extra + n_damping

    damping_coefficients = np.ones((total_vars,)) * 1e-3
    initial_state = damping_coefficients
    #use kalman filter to determine updates to damping coefficients
    transition_matrix = np.eye(total_vars)
    measurement_noise = np.eye(total_vars) * 1e-5
    process_noise = np.eye(total_vars) * 1e-5


    for row in range(measurement_noise.shape[0]):
        if row <= 8:
            measurement_noise[row,row] = 1e-11
        elif row <= 11:
            measurement_noise[row,row] = 1e-8
        elif row < n_measured+n_damping:
            measurement_noise[row,row] = 1e-10
        else:
            measurement_noise[row,row] = 1e-10


    for row in range(process_noise.shape[0]):
        if row < n_measured:
            process_noise[row,row] = 1e-1

        elif row < n_measured+n_damping:
            process_noise[row,row] = 2.5e-5

        else:
            process_noise[row,row] = 1e-16

    initial_state_covariance = measurement_noise

    calibrated_mean.append(initial_state)
    calibrated_var.append(initial_state_covariance)

    tf = my_transition_function(config, measured, n_damping,
                                extra_inferred = extra_inferred,
                                run_local = True)

    norm = [1.0e3 if 'Tension' in col else 1 for col in measured ]

    if s3_object_exist(ukf_savepoint, s3_bucket):
        get_data_s3( ukf_savepoint,
                     ukf_savepoint,
                     s3_bucket)
        arr = np.load(ukf_savepoint)
        calibrated_mean = arr['calibrated_mean']
        calibrated_var = arr['calibrated_var']

        calibrated_mean = calibrated_mean.tolist()
        calibrated_var = calibrated_var.tolist()

    #run ukf to calibrate the fmu
    nsteps = dfsw.shape[0]
    for i in tqdm(range(nsteps)):
        #i=0

        y = dfsw[measure_cols].to_numpy()[i]
        y/=norm
        y = np.array([y,y])

        ukf = kalman('ukf', y,
                     initial_state = np.array(calibrated_mean[-1]),
                     initial_state_covariance = np.array(calibrated_var[-1]),
                     transition_matrix=transition_matrix,
                     measurement_noise=measurement_noise,
                     process_covariance =process_noise,
                     ncpu= -1, #transition_matrix.shape[1]*2+1,
                     use_threads=False
                     )

        # we are setting the state function to be the fmu calculation
        # we are not going to change the observation function since it will
        # be the identity matrix by default
        ukf.state_func = tf.run_fmu
        xhat,xvar = ukf.get_estimate(y)

        updates = xhat[-1]
        updates[n_measured:n_measured+n_damping] = np.clip(updates[n_measured:n_measured+n_damping], 0,0.5)
        calibrated_mean.append(updates)
        calibrated_var.append(xvar[-1])

    #save updated calibration
    np.savez(ukf_savepoint,
            calibrated_mean=calibrated_mean,
            calibrated_var=calibrated_var
            )

    #upload calibration
    send_data_s3( ukf_savepoint,
                  ukf_savepoint,
                  s3_bucket)

#------------------------------------------------------------------------------------------
def make_prediction(dfsw, config, metadata):

    arr = np.load(ukf_savepoint)
    calibrated_mean = arr['calibrated_mean']
    calibrated_var = arr['calibrated_var']

    assetId = metadata['MyCfnAsset']
    sitewise_names = [value for key, value in config.items() if 'result' in key or 'input' in key]
    uncertainty_names = [value for key, value in config.items() if 'uncertainty' in key.lower()]

    damping_coefficients = calibrated_mean[-1][-9:]
    damping_coefficients_std = np.sqrt(np.diag(calibrated_var[-1])[-9:])

    dt = datetime.today()
    now = dt.timestamp()


    df = run_fmu(damping_coefficients, config,'dummy', 0, use_cloud=False)
    fmu_names = df.columns

    for sitewise_name in fmu_names:
        #sitewise_name = fmu_names[0]
        if sitewise_name not in sitewise_names:
            continue
        data = df[sitewise_name]
        #need to makesure we stick with sitewise schema
        data = data.astype('float64')
        t = [0.0]

        # sitewise_name = [x for x in sitewise_names if col in x]
        # #TODO: FIXME
        # if len(sitewise_name) == 0:
        #     continue

        # if isinstance(sitewise_name, list):
        #     sitewise_name=sitewise_name[0]
        data=data.to_numpy()
        print(sitewise_name, data)

        send_asset_property_data( sitewise_name,
                                  t,
                                  data,
                                  assetId=assetId,
                                  use_current_time=False,
                                  use_time=now
                                  )

        if sitewise_name in uncertainty_names:
            idx = uncertainty_names.index(sitewise_name)
            data_std = data + damping_coefficients_std[idx]
            #upper bound uncertainty
            send_asset_property_data( sitewise_name+'_upper',
                                      t,
                                      data_std,
                                      assetId=assetId,
                                      use_current_time=False,
                                      use_time=now
                                      )

            data_std = data - damping_coefficients_std[idx]
            #lower bound uncertainty
            send_asset_property_data( sitewise_name+'_lower',
                                      t,
                                      data_std,
                                      assetId=assetId,
                                      use_current_time=False,
                                      use_time=now
                                      )



#%% main
if __name__ == '__main__':

    import argparse
    parser = argparse.ArgumentParser()
    #parser.add_argument('-s',  dest='s3', type=str, help="s3 bucket" )
    #parser.add_argument('-c',  dest='config', type=str, help="Config File" )
    args = parser.parse_args()

    config = get_user_json_config('iot_config.json')

    metadata = get_cloudformation_metadata('FMUCalibrationStack', region='us-east-1')
    dfsw = get_data(config, metadata)
    calibrate(dfsw, config, metadata)
    make_prediction(dfsw, config, metadata)