#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Aug 30 15:18:24 2023

@author: ubuntu
"""

#generic modules
import json
from tqdm import tqdm

#twinmodule packages
from twinmodules.core.util import get_cloudformation_metadata
from twinmodules.AWSModules.AWS_sitewise import get_asset_propert_id


#%% main
if __name__ == '__main__':

    metadata = get_cloudformation_metadata('FMUCalibrationStack')

    template_name = "MainFMUBoard-template.json"
    with open(template_name,'r') as f:
        template = json.load(f)
    configname = "iot_config.json"
    with open(configname,'r') as f:
        config = json.load(f)

    #cloud formation provides the generated asset id
    assetid = metadata['MyCfnAsset']
    #user twinmodules to determine the property ids
    print("Finding property ids")
    # propertyids = [get_asset_propert_id(config[x],assetid) for x in config.keys()
    #                            if 'result' in x.lower()          \
    #                                or 'input' in x.lower()       \
    #                                or 'uncertainty' in x.lower() ]

    propertyids = {}
    for x in tqdm(config.keys()):
        if 'result' in x.lower() or 'input' in x.lower():
            tmp = get_asset_propert_id(config[x],assetid)
            propertyids[tmp[0]] = tmp[-1]
        elif 'uncertainty' in x.lower():
            tmp = get_asset_propert_id(config[x]+'_lower',assetid)
            propertyids[tmp[0]] = tmp[-1]
            tmp = get_asset_propert_id(config[x]+'_upper',assetid)
            propertyids[tmp[0]] = tmp[-1]

    #convert to dictionary
    #propertyids = {key:value for key, v, value in propertyids}
    print("Generating dashboard json")

    #create an alphabet lookup for grafana numbering
    import string
    from itertools import product
    letters = list(string.ascii_uppercase)
    double_letters = product(letters, letters)
    double_letters = list(map(lambda z: z[0] + z[1], double_letters))
    letters.extend(double_letters)


    #update panel assetIds and property source ids
    dashboard = template.copy()
    new_panels =[]
    for panel in template['panels']:
        #panel = template['panels'][1]
        panel_name = panel['title']
        new_target = []
        overrides = []
        cnt=0
        for name,pid in propertyids.items():
            #name,pid  = list(propertyids.items())[-10]
            #panel['targets']['assetIds'] = [assetid]
            tmp = panel['targets'][0].copy()
            tmp['assetIds'] = [assetid]
            #tmp['refId'] = chr(ord('A') + cnt)
            tmp['refId'] = letters[cnt]
            if 'angular' in panel_name.lower() \
                and '_w'in name.lower():
                    tmp['propertyId'] = pid
                    new_target.append( tmp  )
                    cnt+=1
            if 'damping' in panel_name.lower() \
                and 'b'in name.lower():
                    tmp['propertyId'] = pid
                    new_target.append( tmp  )
                    cnt+=1
            if 'tension' in panel_name.lower() \
                and 'tension'in name.lower():
                    tmp['propertyId'] = pid
                    new_target.append( tmp  )
                    cnt+=1
            if 'slip' in panel_name.lower() \
                and 'slipvelocity'in name.lower():
                    tmp['propertyId'] = pid
                    new_target.append( tmp  )
                    cnt+=1

            #add overrides for uncertainty bands
            if 'damping' in panel_name.lower() and ("_lower" in name or '_upper' in name):
                overrides.append(
                   {
                       "matcher": {
                           "id":"byName",
                           "options": name
                           },
                       "properties":[
                               {
                                "id": "custom.lineStyle",
                                "value": {
                                  "dash": [
                                    10,
                                    10
                                  ],
                                  "fill": "dash"
                                }
                              }
                           ]
                       }
                    )
                if '_upper' in name:
                    var = name.split('_')[0]
                    overrides[-1]['properties'].append(
                        {
                            "id": "custom.fillBelowTo",
                            "value": var+"_lower"
                          }
                        )


        new_panel = panel.copy()
        new_panel['fieldConfig']['overrides'] = overrides
        new_panel['targets'] = new_target
        new_panels.append( new_panel)

    dashboard['panels'] = new_panels

    with open('generated_dashboard2.json', 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=4)