#!/usr/bin/env python3
######################################################################
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. #
# SPDX-License-Identifier: MIT-0                                     #
######################################################################

#generic packages
import json

import aws_cdk as cdk

from twin_maker_scene_stack.twin_maker_scene_stack_stack import TwinMakerSceneStackStack


def get_json(filename):
    with open(filename,'r') as f:
        config = json.load(f)
    return config

json_setup = get_json('../iot_config.json')
json_setup['first_stack'] = 'FMUCalibrationStack'

app = cdk.App()
TwinMakerSceneStackStack(app, "TwinMakerSceneStackStack",
                         json_setup
    # If you don't specify 'env', this stack will be environment-agnostic.
    # Account/Region-dependent features and context lookups will not work,
    # but a single synthesized template can be deployed anywhere.

    # Uncomment the next line to specialize this stack for the AWS Account
    # and Region that are implied by the current CLI configuration.

    #env=cdk.Environment(account=os.getenv('CDK_DEFAULT_ACCOUNT'), region=os.getenv('CDK_DEFAULT_REGION')),

    # Uncomment the next line if you know exactly what Account and Region you
    # want to deploy the stack to. */

    #env=cdk.Environment(account='123456789012', region='us-east-1'),

    # For more information, see https://docs.aws.amazon.com/cdk/latest/guide/environments.html
    )

app.synth()
