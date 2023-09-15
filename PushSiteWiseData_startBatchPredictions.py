# -*- coding: utf-8 -*-
######################################################################
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. #
# SPDX-License-Identifier: MIT-0                                     #
######################################################################

#generic packages
import pandas
from datetime import datetime
import numpy as np

#twinmodule packages
from twinmodules.core.util import get_user_json_config, get_cloudformation_metadata
from twinmodules.AWSModules.AWS_sitewise import send_asset_property_data


#-------------------------------------------------------------------------------

def simulate_data_into_sitewise(assetId, config):

    df= pandas.read_csv("Case_1_Data_2023_06_22.csv", header=1)
    #need to makesure we stick with sitewise schema
    df = df.astype('float64')

    #get to the action
    df = df.tail(2000-1350)

    roller_names = [x for x in df.columns if "Main.R" in x and 'SlipVelocity' not in x]
    sitewise_names = [value for key, value in config.items() if 'measured' in key]

    #TODO: can this be put in parallel?
    chunksize= 3
    t = np.linspace(0,10,num = chunksize)
    for chunk in range(0,df.shape[0],chunksize):

        dt = datetime.today()
        now = dt.timestamp()

        for col in roller_names:
            #col = roller_names[-2]
            print("Chunk {} Variable {}".format(chunk, col))
            number = col.split('R')[-1].split('.')[0]
            roller_data = df[col].iloc[chunk:chunk + chunksize]
            #print(roller_data)
            sitewise_name = [x for x in sitewise_names if number + '_' in x][0]
            send_asset_property_data( sitewise_name,
                                      t,
                                      roller_data,
                                      assetId=assetId,
                                      use_current_time=False,
                                      use_time=now)

#-------------------------------------------------------------------------------
#%% main
if __name__ == '__main__':

    metadata = get_cloudformation_metadata('FMUCalibrationStack')

    config_filename = "iot_config.json"
    config = get_user_json_config(config_filename)

    #add dummy data to IoT SiteWise
    assetId = metadata['MyCfnAsset']
    simulate_data_into_sitewise(assetId, config)