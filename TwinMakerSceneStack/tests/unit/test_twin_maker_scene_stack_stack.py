import aws_cdk as core
import aws_cdk.assertions as assertions

from twin_maker_scene_stack.twin_maker_scene_stack_stack import TwinMakerSceneStackStack

# example tests. To run these tests, uncomment this file along with the example
# resource in twin_maker_scene_stack/twin_maker_scene_stack_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = TwinMakerSceneStackStack(app, "twin-maker-scene-stack")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
