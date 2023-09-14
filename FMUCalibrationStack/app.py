#!/usr/bin/env python3

#twinmodule packages
from twinmodules.core.util import get_user_json_config

#CDK packages
from constructs import Construct
from aws_cdk import App, Stack, Duration, Aspects
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iotsitewise as iotsitewise
from aws_cdk import aws_batch_alpha as batch
from aws_cdk import aws_batch as batchorg
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_iam as iam
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_grafana as grafana
#security checks
from cdk_nag import AwsSolutionsChecks, NagSuppressions



class FMUCalibrationStack(Stack):

    def __init__(self, scope: Construct, id: str, json_setup:dict, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)


        #generate new vpc
        self.vpc = ec2.Vpc(self, "VPC",
                           )
        self.vpc.add_flow_log('fmuVPCflowlog')


        # Create an S3 bucket
        s3_bucket = s3.Bucket(
            self,
            json_setup['s3_bucket_name'],
            versioned=True,
            server_access_logs_prefix = 'access_logs_',
            enforce_ssl = True,
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
        job_definition = batchorg.CfnJobDefinition(self, "JobDefinition",
                                                   type="container",
                                                   container_properties=batchorg.CfnJobDefinition.ContainerPropertiesProperty(
                                                                   image=json_setup['calibration_container_image'],
                                                                   #TODO: make this modifiable from json
                                                                   command=['python3.10', 'fmu_calibrate.py'],
                                                                   #execution_role_arn= batch_compute_environment.instance_role,
                                                                   log_configuration=batchorg.CfnJobDefinition.LogConfigurationProperty(
                                                                       log_driver="awslogs"),
                                                                   vcpus=json_setup['vCPU'],
                                                                   memory=json_setup['Mem'])
                                                  )

        # Create an EventBridge rule to trigger the Batch job
        rule = events.Rule(
            self, "EventRule",
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


        # Create Grafana dashboard for post-processing

        #https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_grafana/CfnWorkspace.html
        #https://docs.aws.amazon.com/grafana/latest/APIReference/API_CreateWorkspace.html

        grafana_instance = grafana.CfnWorkspace(self, "Grafana-FMU-Workspace",
                                                name = "Grafana-FMU-Workspace",
                                                account_access_type="CURRENT_ACCOUNT",
                                                authentication_providers=["AWS_SSO"],
                                                permission_type="SERVICE_MANAGED",
                                                role_arn = self.create_grafana_role(), #grafana_role.role_arn,
                                                data_sources=["SITEWISE"]
                                                )


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
            assumed_by=iam.ServicePrincipal("grafana.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AWSIoTSiteWiseReadOnlyAccess")
            ]
        )
        return grafana_role.role_arn


#%% setup json inputs
#------------------------------------------------------------------------------
json_setup = get_user_json_config('../iot_config.json')

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
                    description  = "Guidance for Self-Calibrating Level 4 Digital Twins on AWS (SO1903)")
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
app.synth()