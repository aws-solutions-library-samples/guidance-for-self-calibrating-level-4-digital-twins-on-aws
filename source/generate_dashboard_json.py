#!/usr/bin/env python3
# -*- coding: utf-8 -*-
######################################################################
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. #
# SPDX-License-Identifier: MIT-0                                     #
######################################################################

#generic modules
import json
from tqdm import tqdm
import string
from itertools import product
import os
import boto3

#twinmodule packages
from twinmodules.AWSModules.AWS_sitewise import get_asset_propert_id


def copy_json_to_s3(local_file_path, bucket_name, s3_file_key):
    """
    Copy a JSON file to an S3 bucket.

    :param local_file_path: Path to the local JSON file
    :param bucket_name: Name of the S3 bucket
    :param s3_file_key: The key (path) where the file will be stored in S3
    :return: True if successful, False otherwise
    """
    # Initialize the S3 client
    s3_client = boto3.client('s3')

    try:
        # Verify that the local file exists
        if not os.path.exists(local_file_path):
            print(f"Error: The file {local_file_path} does not exist.")
            return False

        # Verify that the file is a valid JSON
        with open(local_file_path, 'r') as file:
            json.load(file)  # This will raise an exception if the JSON is invalid

        # Upload the file to S3
        s3_client.upload_file(local_file_path, bucket_name, s3_file_key)

        print(f"Successfully uploaded {local_file_path} to s3://{bucket_name}/{s3_file_key}")
        return True

    except json.JSONDecodeError:
        print(f"Error: The file {local_file_path} is not a valid JSON file.")
        return False
    except boto3.exceptions.S3UploadFailedError as e:
        print(f"Error uploading file to S3: {str(e)}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}")
        return False

def get_asset_id(stack_name, asset_logical_id="MyCfnAsset"):
    # Initialize CloudFormation and IoT SiteWise clients
    cf_client = boto3.client('cloudformation')
    sitewise_client = boto3.client('iotsitewise')

    try:
        # Get the physical ID of the asset from CloudFormation
        response = cf_client.describe_stack_resource(
            StackName=stack_name,
            LogicalResourceId=asset_logical_id
        )
        physical_id = response['StackResourceDetail']['PhysicalResourceId']

        # Use the physical ID to get the asset details from IoT SiteWise
        response = sitewise_client.describe_asset(assetId=physical_id)
        asset_name = response['assetName']

        # Verify if the asset name matches "web-handling-Asset"
        if asset_name == "web-handling-Asset":
            return physical_id
        else:
            # If the asset name doesn't match, search for it
            paginator = sitewise_client.get_paginator('list_assets')
            for page in paginator.paginate():
                for asset in page['assetSummaries']:
                    if asset['name'] == "web-handling-Asset":
                        return asset['id']

        raise Exception("Asset 'web-handling-Asset' not found")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return None

#%% main
if __name__ == '__main__':

    stack_name = 'FMUCalibrationStack'

    template_name = "./assets/MainFMUBoard-template.json"
    configname = "iot_config.json"
    if not os.path.isfile(template_name):
        raise ValueError(f"ERROR: couldnt find {template_name} "
                         +"try running this file one directory higher.")
    if not os.path.isfile(configname):
        raise ValueError(f"ERROR: couldnt find {template_name} "
                         +"try running this file one directory higher.")

    with open(template_name,'r') as f:
        template = json.load(f)
    with open(configname,'r') as f:
        config = json.load(f)

    #cloud formation provides the generated asset id
    assetid = get_asset_id(stack_name)
    #use twinmodules to determine the property ids
    print("Finding property ids")

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

    print("Generating dashboard json")

    #create an alphabet lookup for grafana numbering
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
            tmp = panel['targets'][0].copy()
            tmp['assetIds'] = [assetid]
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
        if 'fieldConfig' in new_panel.keys():
            new_panel['fieldConfig']['overrides'] = overrides
        new_panel['targets'] = new_target
        new_panels.append( new_panel)

    dashboard['panels'] = new_panels

    local_file_path = 'generated_dashboard.json'
    with open(local_file_path, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=4)

    cf_client = boto3.client('cloudformation')
    stack_resources = cf_client.describe_stack_resources(StackName=stack_name)
    s3_bucket_resource = next((r for r in stack_resources['StackResources'] if r['ResourceType'] == 'AWS::S3::Bucket'), None)
    s3_bucket_name = s3_bucket_resource['PhysicalResourceId']

    copy_json_to_s3(local_file_path, s3_bucket_name, local_file_path)


    dt_iam_resource = next((r for r in stack_resources['StackResources']
                        if r['ResourceType'] == 'AWS::IAM::Role'
                        and 'DemoTwinMakerRole' in r['LogicalResourceId']), None)
    dt_iam_arn = dt_iam_resource['PhysicalResourceId']

    print(f"\nThe IAM ARN to copy into Grafana is: {dt_iam_arn}\n")



