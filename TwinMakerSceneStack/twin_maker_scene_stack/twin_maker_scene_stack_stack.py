######################################################################
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. #
# SPDX-License-Identifier: MIT-0                                     #
######################################################################

from aws_cdk import Stack
from aws_cdk import aws_iottwinmaker as twinmaker
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_s3 as s3
from constructs import Construct
import boto3
from botocore.exceptions import ClientError
import os

def get_metadata(stack_name: str) -> tuple:
    """
    Retrieves the S3 bucket name and TwinMaker workspace ID from a given CloudFormation stack.

    :param stack_name: Name of the CloudFormation stack
    :return: A tuple containing the S3 bucket name and TwinMaker workspace ID
    """
    cfn_client = boto3.client('cloudformation')
    s3_bucket = None
    twinmaker_workspace_id = None

    try:
        # Describe all resources in the stack
        response = cfn_client.describe_stack_resources(StackName=stack_name)

        # Extract the resources
        resources = response['StackResources']

        # Find the S3 bucket and TwinMaker workspace ID in the resources
        for resource in resources:
            if resource['ResourceType'] == 'AWS::S3::Bucket':
                s3_bucket = resource['PhysicalResourceId']
            elif resource['ResourceType'] == 'AWS::IoTTwinMaker::Workspace':
                twinmaker_workspace_id = resource['PhysicalResourceId']

        if not s3_bucket:
            raise ValueError("S3 bucket not found in stack resources")
        if not twinmaker_workspace_id:
            raise ValueError("TwinMaker workspace ID not found in stack resources")

    except ClientError as e:
        print(f"An error occurred: {e}")
        raise
    except KeyError as e:
        print(f"Expected key not found in the response: {e}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise

    return s3_bucket, twinmaker_workspace_id




class TwinMakerSceneStackStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, json_setup: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


        s3_bucket, twinmaker_workspace_id = get_metadata(json_setup['first_stack'])

        scene_name = json_setup['twinmaker_3d_scene'].split('/')[-1]

        # Deploy the scene content to S3
        s3_deployment_scene = s3deploy.BucketDeployment(
            self, "DeploySceneContent",
            sources=[s3deploy.Source.asset(os.path.dirname(json_setup['twinmaker_3d_scene']))],
            destination_bucket=s3.Bucket.from_bucket_name(self, "DestinationBucket", s3_bucket),
            destination_key_prefix="twinmaker/scenes"
        )


        # Create a TwinMaker Scene
        scene = twinmaker.CfnScene(
            self, "WebHandlingScene",
            content_location=f"s3://{s3_bucket}/twinmaker/scenes/{scene_name}",
            scene_id="web-handling-scene",
            workspace_id=twinmaker_workspace_id
        )
        scene.node.add_dependency(s3_deployment_scene)

