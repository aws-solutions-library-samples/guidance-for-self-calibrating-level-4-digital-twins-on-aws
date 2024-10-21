#!/usr/bin/env python3
######################################################################
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. #
# SPDX-License-Identifier: MIT-0                                     #
######################################################################

#generic packages
import json
import os

#CDK packages
from constructs import Construct
from aws_cdk import App, Stack, Duration, Aspects
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iotsitewise as iotsitewise
from aws_cdk import aws_batch as batch
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_iam as iam
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_grafana as grafana
from aws_cdk import aws_iottwinmaker as twinmaker
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import RemovalPolicy
from aws_cdk import custom_resources as cr
#security checks
from cdk_nag import AwsSolutionsChecks, NagSuppressions

import boto3

def get_aws_account_and_region():
    sts = boto3.client('sts')
    account_id = sts.get_caller_identity()["Account"]
    region = boto3.session.Session().region_name
    return account_id, region

account_id, region = get_aws_account_and_region()

class FMUCalibrationStack(Stack):

    def __init__(self, scope: Construct, id: str, json_setup:dict, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)


        #generate new vpc
        self.vpc = ec2.Vpc(self, "VPC",
                           )

        self.grafana_role =self.create_grafana_role()
        self.twinmaker_role = self.create_twinmaker_role()


        # Create an S3 bucket
        s3_bucket = s3.Bucket(
            self,
            json_setup['s3_bucket_name'],
            #versioned=True,
            #server_access_logs_prefix = 'access_logs_',
            enforce_ssl = True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        # Grant the custom resource the necessary permissions to delete the bucket contents
        cr.AwsCustomResource(self, "BucketCleanup",
            on_delete=cr.AwsSdkCall(
                service="S3",
                action="deleteObjects",
                parameters={
                    "Bucket": s3_bucket.bucket_name,
                    "Delete": {
                        "Objects": [{"Key": "dummy"}]
                    }
                },
                physical_resource_id=cr.PhysicalResourceId.of(s3_bucket.bucket_name)
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            )
        )


        # Create an AWS Batch compute environment
        batch_compute_environment = batch.ManagedEc2EcsComputeEnvironment(
            self,
            json_setup['batch_name'],
            vpc=self.vpc,
            instance_role = self.create_batch_instance_role(),
            minv_cpus=json_setup['batch_compute_min_vcpu'],
            maxv_cpus=json_setup['batch_compute_max_vcpu'],
            allocation_strategy=batch.AllocationStrategy.BEST_FIT_PROGRESSIVE
        )
        #add queue to the compute environment
        job_queue = batch.JobQueue(self,
                                    "JobQueue-" +json_setup['batch_name'],
                                    priority=10
                                    )
        job_queue.add_compute_environment(batch_compute_environment, 1)

        #define Batch job
        #https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_batch/CfnJobDefinition.html
        job_definition = batch.CfnJobDefinition(self, "JobDefinitionL4DT",
                                                   type="container",
                                                   container_properties=batch.CfnJobDefinition.ContainerPropertiesProperty(
                                                                   image=json_setup['calibration_container_image'],
                                                                   #TODO: make this modifiable from json
                                                                   command=['python3.10', 'fmu_calibrate.py'],
                                                                   #execution_role_arn= batch_compute_environment.instance_role,
                                                                   log_configuration=batch.CfnJobDefinition.LogConfigurationProperty(
                                                                       log_driver="awslogs"),
                                                                   vcpus=json_setup['vCPU'],
                                                                   memory=json_setup['Mem'])
                                                  )

        # Create an EventBridge rule to trigger the Batch job
        rule = events.Rule(
            self, "EventRuleL4DT",
            schedule=events.Schedule.rate( Duration.minutes(int(json_setup['scheduler_waittime_min']) ) )
        )

        # Add the Batch job as a target for the EventBridge rule
        rule.add_target(targets.BatchJob(
            job_queue.job_queue_arn, job_queue,
            job_definition.ref,
            job_definition
        ))


        # Setup IoT SiteWise
        # Create an Asset Model

        #setup properties
        iot_model_properties = []
        iot_asset_properties = []
        for i, prop in enumerate(json_setup['asset_properties']):
            if 'velocity' in prop.lower():
                units = 'm/s'
            elif 'tension' in prop.lower():
                units = 'N'
            elif '_w' in prop.lower():
                units = 'rad/s'
            else:
                units = 'coef'
            iot_model_properties.append(
                    iotsitewise.CfnAssetModel.AssetModelPropertyProperty(
                        data_type="DOUBLE",
                        logical_id=prop,
                        name=prop,
                        type=iotsitewise.CfnAssetModel.PropertyTypeProperty(
                            type_name="Measurement"
                        ),
                        unit=units
                ))

            iot_asset_properties.append(
                iotsitewise.CfnAsset.AssetPropertyProperty(
                    logical_id=prop
                ))

        cfn_asset_model = iotsitewise.CfnAssetModel(self, "MyCfnAssetModel",
            asset_model_name=json_setup['sitewise_name'],
            asset_model_description="Web-handling rollers",
            asset_model_properties=iot_model_properties
            )

        # Create an Asset using the Asset Model
        cfn_asset = iotsitewise.CfnAsset(self, "MyCfnAsset",
            asset_model_id=cfn_asset_model.attr_asset_model_id,
            asset_name="web-handling-Asset",
            # the properties below are optional
            asset_description="assetDescription",
            asset_properties=iot_asset_properties
        )

        #twinmaker_workspace, model_component_type = self.create_twinmaker_workspace(json_setup['twinmaker_workspace_name'], s3_bucket)
        twinmaker_workspace = self.create_twinmaker_workspace(json_setup['twinmaker_workspace_name'], s3_bucket)
        twinmaker_workspace.node.add_dependency(s3_bucket)

        # Upload 3D model to S3
        s3_deployment = s3deploy.BucketDeployment(
            self, "DeployModel",
            sources=[s3deploy.Source.asset(os.path.dirname(json_setup['twinmaker_3d_model']))],
            destination_bucket=s3_bucket,
            destination_key_prefix="twinmaker/3d-models"
        )


        model_name = json_setup['twinmaker_3d_model'].split('/')[-1]

        entity = twinmaker.CfnEntity(
                self, "TwinMakerEntity",
                entity_name="WebHandlingEntity",
                workspace_id=twinmaker_workspace.workspace_id,
                components={
                    "sitewiseComponent": twinmaker.CfnEntity.ComponentProperty(
                        component_name="sitewiseComponent",
                        component_type_id="com.amazon.iotsitewise.connector",
                        properties={
                            "sitewiseAssetId": twinmaker.CfnEntity.PropertyProperty(
                                value=twinmaker.CfnEntity.DataValueProperty(
                                    string_value=cfn_asset.attr_asset_id
                                )
                            ),
                            "sitewiseAssetModelId": twinmaker.CfnEntity.PropertyProperty(
                                value=twinmaker.CfnEntity.DataValueProperty(
                                    string_value=cfn_asset_model.attr_asset_model_id  # Assuming you have an asset model resource
                                )
                            )
                        }
                    ),
                    # "3DModel": twinmaker.CfnEntity.ComponentProperty(
                    #     component_name="3DModel",
                    #     component_type_id="com.example.iottwinmaker.3dmodel",
                    #     properties={
                    #         "s3Arn": twinmaker.CfnEntity.PropertyProperty(
                    #             value=twinmaker.CfnEntity.DataValueProperty(
                    #                 string_value=f"arn:aws:s3:::{s3_bucket.bucket_name}/twinmaker/3d-models/{model_name}"
                    #             )
                    #         )
                    #     }
                    # )
                }
            )

        entity.add_dependency(twinmaker_workspace)
        entity.node.add_dependency(s3_deployment)


        # Deploy the scene content to S3
        # s3_deployment_scene = s3deploy.BucketDeployment(
        #     self, "DeploySceneContent",
        #     sources=[s3deploy.Source.asset(os.path.dirname(json_setup['twinmaker_3d_scene']))],
        #     destination_bucket=s3_bucket,
        #     destination_key_prefix="twinmaker/scenes"
        # )

        #scene_name = json_setup['twinmaker_3d_scene'].split('/')[-1]
        # Create a TwinMaker Scene
        # scene = twinmaker.CfnScene(
        #     self, "WebHandlingScene",
        #     content_location=f"s3://{s3_bucket.bucket_name}/twinmaker/scenes/{scene_name}",
        #     scene_id="web-handling-scene",
        #     workspace_id=twinmaker_workspace.workspace_id
        # )

        # # Ensure the scene is created after the workspace and entity
        # scene.add_dependency(twinmaker_workspace)
        # scene.add_dependency(entity)
        # scene.node.add_dependency(s3_deployment_scene)




        # Create Grafana dashboard for post-processing

        #https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_grafana/CfnWorkspace.html
        #https://docs.aws.amazon.com/grafana/latest/APIReference/API_CreateWorkspace.html

        grafana_instance = grafana.CfnWorkspace(self, "Grafana-FMU-Workspace",
                                                name = "Grafana-FMU-Workspace",
                                                account_access_type="CURRENT_ACCOUNT",
                                                authentication_providers=["AWS_SSO"],
                                                permission_type="SERVICE_MANAGED",
                                                role_arn = self.grafana_role.role_arn,
                                                data_sources=["SITEWISE"],
                                                plugin_admin_enabled = True
                                                )


        # Add CORS configuration to S3 bucket after Grafana workspace is created
        self.add_cors_to_s3_bucket(s3_bucket, grafana_instance)

    def create_twinmaker_workspace(self, workspace_name, s3_bucket):
        workspace = twinmaker.CfnWorkspace(
            self, "DemoTwinMakerWorkspace",
            workspace_id=workspace_name,
            role=self.twinmaker_role.role_arn,
            s3_location=f"arn:aws:s3:::{s3_bucket.bucket_name}"
        )

        # Create the 3D model component type
        #model_component_type = self.create_3d_model_component_type(workspace.workspace_id)

        # Ensure the component type is created after the workspace
        #model_component_type.add_dependency(workspace)

        return workspace #, model_component_type

    def create_3d_model_component_type(self, workspace_id):
        return twinmaker.CfnComponentType(
            self, "3DModelComponentType",
            workspace_id=workspace_id,
            component_type_id="com.example.iottwinmaker.3dmodel",
            description="3D Model Component Type",
            property_definitions={
                "s3Arn": {
                    "dataType": {
                        "type": "STRING"
                    },
                    "is_time_series": False
                }
            }
        )

    def create_twinmaker_role(self):
        twinmaker_role = iam.Role(
            self, "DemoTwinMakerRole",
            #assumed_by=iam.ServicePrincipal("iottwinmaker.amazonaws.com"),
            assumed_by=iam.CompositePrincipal(
                    iam.ServicePrincipal("iottwinmaker.amazonaws.com"),
                    iam.ServicePrincipal("grafana.amazonaws.com"),
                    iam.AccountPrincipal(account_id),
                    iam.ArnPrincipal(f"arn:aws:iam::{account_id}:role/service-role/AmazonGrafanaServiceRole-2uDOB8x9f"),
                    #iam.ArnPrincipal(f"arn:aws:iam::{account_id}:role/service-role/{grafanakey}")
                    iam.ArnPrincipal(self.grafana_role.role_arn)
                ),
        )
        twinmaker_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AWSIoTSiteWiseReadOnlyAccess"))
        twinmaker_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess"))
        twinmaker_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "iottwinmaker:*",
            ],
            resources=["*"]
        ))

        # twinmaker_role.assume_role_policy.add_statements(iam.PolicyStatement(
        #     actions=["sts:AssumeRole"],
        #     effect=iam.Effect.ALLOW,
        #     principals=[iam.ServicePrincipal("grafana.amazonaws.com")]
        # ))
        return twinmaker_role

    def create_batch_instance_role(self):
         '''any of the AWS Batch jobs will require the ability to read,
         write, overwrite, or delete from s3 buckets

         They also require the ability to push data into sitewise from any
         ec2 resource in this demo.
         '''
         batch_instance_role = iam.Role(
             self,
             "FMU-BatchInstanceRole",
             assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
         )
         batch_instance_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess"))
         batch_instance_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonEC2ContainerServiceforEC2Role"))
         batch_instance_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy"))
         batch_instance_role.add_to_policy(iam.PolicyStatement(
             actions=[
                      "iotsitewise:BatchPutAssetPropertyValue",
                      "iotsitewise:Describe*",
                      "iotsitewise:Get*",
                      "iotsitewise:ListTimeSeries",
                      "iotsitewise:ListAssets",
                      "cloudformation:ListStackResources"
                      ],
             resources=["*"],
         ))
         return batch_instance_role


    def create_grafana_role(self):
        grafana_role = iam.Role(
            self, "GrafanaFMURole",
            #assumed_by=iam.ServicePrincipal("grafana.amazonaws.com"),
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("grafana.amazonaws.com"),
                iam.AccountPrincipal(account_id)
            ),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AWSIoTSiteWiseReadOnlyAccess"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3ReadOnlyAccess")
            ]
        )
        grafana_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "iottwinmaker:*",
            ],
            resources=["*"]
        ))
        # # Add permission to assume the TwinMaker role
        # grafana_role.add_to_policy(iam.PolicyStatement(
        #     actions=["sts:AssumeRole"],
        #     resources=[self.twinmaker_role.role_arn]  # Assuming you have a reference to the TwinMaker role
        # ))
        # Add a statement to allow Grafana to assume this role
        # grafana_role.assume_role_policy.add_statements(iam.PolicyStatement(
        #     actions=["sts:AssumeRole"],
        #     effect=iam.Effect.ALLOW,
        #     principals=[iam.ServicePrincipal("grafana.amazonaws.com")]
        # ))
        #return grafana_role.role_arn
        return grafana_role


    def add_cors_to_s3_bucket(self, bucket, grafana_workspace):
        cors_configuration = [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "HEAD"],
                "AllowedOrigins": [f"https://{grafana_workspace.attr_endpoint}"],
                "ExposeHeaders": ["ETag"],
                "MaxAgeSeconds": 3000
            }
        ]

        cr.AwsCustomResource(
            self, "S3BucketCorsConfiguration",
            on_create=cr.AwsSdkCall(
                service="S3",
                action="putBucketCors",
                parameters={
                    "Bucket": bucket.bucket_name,
                    "CORSConfiguration": {
                        "CORSRules": cors_configuration
                    }
                },
                physical_resource_id=cr.PhysicalResourceId.of(f"{bucket.bucket_name}-cors")
            ),
            on_update=cr.AwsSdkCall(
                service="S3",
                action="putBucketCors",
                parameters={
                    "Bucket": bucket.bucket_name,
                    "CORSConfiguration": {
                        "CORSRules": cors_configuration
                    }
                },
                physical_resource_id=cr.PhysicalResourceId.of(f"{bucket.bucket_name}-cors")
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=[bucket.bucket_arn]
            )
        )

def get_json(filename):
    with open(filename,'r') as f:
        config = json.load(f)
    return config

#%% setup json inputs
#------------------------------------------------------------------------------
json_setup = get_json('../iot_config.json')

asset_lst = []
#define virtual sensor digital predictions
for key, value in json_setup.items():
    if 'result' in key.lower() or 'input' in key.lower():
        asset_lst.append(value)
    elif 'uncertainty' in key.lower():
        #add uncertainty bounds
        asset_lst.append(value+"_lower")
        asset_lst.append(value+"_upper")
json_setup['asset_properties'] = asset_lst

#%% synthesize the cloud formation script
app = App()
stack = FMUCalibrationStack(app, "FMUCalibrationStack", json_setup,
                    description  = "Guidance for Self-Calibrating Level 4 Digital Twins on AWS (SO9323)")
Aspects.of(app).add(AwsSolutionsChecks())
NagSuppressions.add_stack_suppressions(stack,
                                           [{ 'id':"AwsSolutions-IAM4",
                                               'reason':"This is example code that a customer "
                                               +"needs to customize for their application."}
                                            ])
NagSuppressions.add_stack_suppressions(stack,
                                           [{ 'id':"AwsSolutions-IAM5",
                                               'reason':"This is example code that a customer "
                                               +"needs to customize for their application."}
                                            ])
NagSuppressions.add_stack_suppressions(stack,
                                           [{ 'id':"AwsSolutions-L1",
                                               'reason':"This is example code that a customer "
                                               +"needs to customize for their application."}
                                            ])
NagSuppressions.add_stack_suppressions(stack,
                                           [{ 'id':"AwsSolutions-VPC7",
                                               'reason':"This is example code that a customer "
                                               +"needs to customize for their application."}
                                            ])
NagSuppressions.add_stack_suppressions(stack,
                                           [{ 'id':"AwsSolutions-S1",
                                               'reason':"This is example code that a customer "
                                               +"needs to customize for their application."}
                                            ])
app.synth()