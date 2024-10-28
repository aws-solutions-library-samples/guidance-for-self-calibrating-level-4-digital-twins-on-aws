#!/usr/bin/env python3
######################################################################
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. #
# SPDX-License-Identifier: MIT-0                                     #
######################################################################
import json
import boto3
import os


def find_entity_id(workspace_id, entity_name):
    # Create a TwinMaker client
    client = boto3.client('iottwinmaker')

    try:
        # Call the ListEntities API
        response = client.list_entities(
            workspaceId=workspace_id,
        )

        # Check if any entities were found
        if 'entitySummaries' in response and len(response['entitySummaries']) > 0:
            # Return the entity ID of the first matching entity
            return response['entitySummaries'][0]['entityId']
        else:
            print(f"No entity found with name: {entity_name}")
            return None

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return None



def update_twinmaker_scene(scene_file_path, stack_name, property_names):
    # Load existing JSON
    with open(scene_file_path, 'r') as file:
        scene_data = json.load(file)

    # Initialize boto3 clients
    cf_client = boto3.client('cloudformation')
    sitewise_client = boto3.client('iotsitewise')

    # Get S3 bucket name from CloudFormation stack
    try:
        stack_resources = cf_client.describe_stack_resources(StackName=stack_name)

        s3_bucket_resource = next((r for r in stack_resources['StackResources'] if r['ResourceType'] == 'AWS::S3::Bucket'), None)

        if s3_bucket_resource:
            s3_bucket_name = s3_bucket_resource['PhysicalResourceId']

            # Update S3 URI in scene data
            for node in scene_data['nodes']:
                for component in node.get('components', []):
                    if component['type'] == 'ModelRef' and 's3://' in component['uri']:
                        component['uri'] = f"s3://{s3_bucket_name}/twinmaker/3d-models/rollerTwin.gltf"
        else:
            print("S3 bucket not found in stack resources")
    except Exception as e:
        print(f"Error fetching S3 bucket from CloudFormation: {str(e)}")

    # Get SiteWise asset ID from CloudFormation stack
    try:
        twinmaker_workspace_id = next((r for r in stack_resources['StackResources'] if r['ResourceType'] == 'AWS::IoTTwinMaker::Workspace'), None)
        if twinmaker_workspace_id:
            twinmaker_workspace_id = twinmaker_workspace_id['PhysicalResourceId']


        entity_id = find_entity_id(twinmaker_workspace_id, "WebHandlingEntity")

        scene_data['properties']["dataBindingConfig"]["template"]["sel_entity"] = entity_id

        sitewise_asset_resource = next((r for r in stack_resources['StackResources'] if r['ResourceType'] == 'AWS::IoTSiteWise::Asset'), None)

        if sitewise_asset_resource:
            asset_id = sitewise_asset_resource['PhysicalResourceId']

            # Get SiteWise property IDs
            asset_description = sitewise_client.describe_asset(assetId=asset_id)
            property_ids = {prop['name']: prop['id'] for prop in asset_description['assetProperties']}

            # Update property IDs in scene data
            for node in scene_data['nodes']:
                for component in node.get('components', []):
                    if component['type'] == 'Tag' and 'valueDataBinding' in component:
                        property_name = component['valueDataBinding']['dataBindingContext']['propertyName']
                        if property_name in property_ids:
                            component['valueDataBinding']['dataBindingContext']['propertyId'] = property_ids[property_name]
                            component['valueDataBinding']['dataBindingContext']['entityId'] = entity_id

        else:
            print("SiteWise asset not found in stack resources")
    except Exception as e:
        print(f"Error fetching SiteWise asset info: {str(e)}")


    # Save updated JSON
    filename = os.path.basename(scene_file_path)
    output_dir = "./assets/twinmakerscene/"

    # Create the directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Construct the full path for the output file
    output_path = os.path.join(output_dir, f"generated_{filename}")

    # Write the JSON data to the file
    with open(output_path, 'w') as file:
        json.dump(scene_data, file, indent=2)



#%% main
if __name__ == '__main__':

    # Example usage
    scene_file_path = './assets/FirstScene.json'
    stack_name = 'FMUCalibrationStack'
    property_names = [f'Roller{i}_w' for i in range(1, 11)]

    update_twinmaker_scene(scene_file_path, stack_name, property_names)