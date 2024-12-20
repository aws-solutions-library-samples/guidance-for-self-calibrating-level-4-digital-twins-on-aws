# Guidance for Self-Calibrating Level 4 Digital Twins on AWS with TwinFlow

## Table of Content

### Required

1. [Overview](#overview)
    - [Architecture](Architecture)
    - [Cost](#cost)
2. [Prerequisites](#prerequisites)
    - [Operating System](#operating-system)
3. [Deployment Steps](#deployment-steps)
4. [Deployment Validation](#deployment-validation)
5. [Running the Guidance](#running-the-guidance)
6. [Description of TwinFlow Script](#description-of-twinflow-script)
7. [Next Steps](#next-steps)
8. [Cleanup](#cleanup)


## Overview

Digital twins can be a powerful method to provide risk assessment, virtual sensors, scenario analysis, and process or design optimization.  However, digital twins are only as smart as the initial setup and assumptions used to develop them.  Hence, it is often (not always) better to combine a digital twin with measurments to modify either the assumptions internal to the digital twin or modify the predictions of the digital twin. 

This guide demonstrates both how to deploy the infrastructure needed to combine a IoT data with a physics based digital twin _and_ how to probablistically calibrate the digital twin with an Unscented Kalman Filter. 

Standard AWS CDK is used to deploy the infrastructure needed for scalable compute including an IoT database.  The opensource tool AWS [TwinFlow](https://github.com/aws-samples/twinflow) is used to achieve the self-calibration of the digital twin.  A blog discussing the overall concepts of this guide can be found [here](https://aws.amazon.com/blogs/hpc/deploying-level-4-digital-twin-self-calibrating-virtual-sensors-on-aws/).

### Architecture
</br>
<center>
<img src="./assets/images/architecture.PNG" width=600>
</center>
</br>

1. Users download TwinFlow from GitHub and install on their temporary Amazon EC2 interface
2. Users can modify the example containers for their specific application including embedding a digital twin inside the container. The example TwinFlow containers use probabilistic methods to calibrate the digital twin. 
3. Next, push the container to Amazon Elastic Container Registry to enable using the container by all AWS services.
4. Data from an edge location is ingested to  AWS IoT SiteWise
5. Using Amazon EventBridge scheduler, periodically deploy an Amazon EC2 instance in AWS Batch which loads the TwinFlow container and application customized code.
6. The TwinFlow container loads the AWS IoT SiteWise data, calibrates a digital twin, and stores the calibration in an Amazon S3 bucket.
7. Using an autoscaling EC2 in a AWS Batch compute environment, use the calibrated digital twin to make physics predictions
8. Upload the physics predictions into AWS IoT SiteWise enabling downstream consumption
9. Monitor the data in Amazon Managed Grafana with AWS IoT TwinMaker
10. Users can stop their initial Amazon EC2 instance as it is no longer needed. 

### Cost

You are responsible for the cost of the AWS services used while running this Guidance. As of 10/13/23, the cost for running this Guidance with the default settings in the us-east-1 is less than $10 per month.

The cost of this solution is mainly dependant on:

* The number of incoming IoT data streams
* Frequency of IoT data streams
* Runtime of the digital twin
* Number of variables being calibrated within the digital twin

In this specific example, discussed in depth [here](https://aws.amazon.com/blogs/hpc/deploying-level-4-digital-twin-self-calibrating-virtual-sensors-on-aws/), we are using a small number of IoT datastreams (9 streams), being sampled at 20min intervals, and calibrating a medium/small number of variables (9 variables). Our digital twin has a runtime of around a few seconds. Thus, the actual monthly cost of this solution is less then $10/month.  Costs can dramatically change depending on modification of any of these dependancies.

## Prerequisites

### Operating System

While the solution has been tested with Linux on an EC2 instance, there is no reason Windows cannot be used.  AWS TwinFlow and AWS CDK are python applications that are OS independant.

The digital twin is embedded and deployed in a linux container, which also enables OS independance. 

### AWS account requirments

This solution assumes the user has IAM admin rights to their account and enables the deployment of a variety of AWS services within the account. 

### AWS CDK installation

Run the following commands to install CDK

This step installs the AWS command line options.
```
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```
You can now run the command ```aws configure``` to setup the IAM permissions for your account on this specific EC2 instance. 


Now install npm:
```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.37.2/install.sh | bash
. ~/.nvm/nvm.sh
nvm install node
node -v
npm -v
```
Finally, install the cdk CLI:
```
npm install -g aws-cdk
```


## Deployment Steps:


1) Build and push containers to ECR

The example container ```Dockerfile-fmu-calibrater``` includes both building and installation of TwinFlow and embedding the example digital twin.  This digital twin is in the form of an FMU for this example.

If you are running on an EC2 instance in the cloud, use the aws CLI to quickly build and push to your accounts AWS ECR (note via console navigate to ECR and create a repository name for this demo). For example, the following commands build the docker and push to an ECR repo called "fmucalibrate". Update the account number and region. <br>
```
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account number>.dkr.ecr.us-east-1.amazonaws.com
docker build -t fmucalibrate .
docker tag fmucalibrate:latest <account number>.dkr.ecr.us-east-1.amazonaws.com/fmucalibrate:latest
docker push <account number>.dkr.ecr.us-east-1.amazonaws.com/fmucalibrate:latest
```

2) Review the user defined options in the ```iot_config.json```.  Note this file contains cloud specific configuration that need to be set based on your account configuration.  Such as the address for your container images, the account region, s3 bucket names, etc.  This file also includes the specific inputs and outputs for the FMU file that will need to be customized to your application.  You can also control numerical configuration for running the FMU such as step stize, solution converge tolerance, number of iterations to wait for convergence, etc. Notice that the exact address of the container in ECR will change depending on your account and thus, even if you are not trying to customize this guidance, you will need to update the address with your specific account number. 

</br>
<center>
<img src="./assets/images/screenshot_iot_config.PNG" width=600>
</center>
</br>

3) Install python packages and deploy CDK IaC

Install CDK Python packages:
```
pip install aws-cdk-lib cdk-nag
```

Deploy entire infrastructure. Note the cdk bootstrap command is only required once per initial account setup. The synth command generates a cloud formation yaml file.  The cdk deploy command executes the cloud formation yaml file.

```
cd FMUCalibrationStack
cdk bootstrap
cdk synth
cdk deploy
cd ..
```

During CDK deployment, you can monitor the progress, status, and any errors by navigating to the CloudFormation page in the AWS Console. This CDK deployment will create a TwinMaker instance using the 3D asset located in the "./assets/3dassets" directory.

Grafana directly reads data from SiteWise for both physical and virtual sensors. The 3D asset is deployed through TwinMaker.

It's important to note that this CDK setup uses a dummy data submission script instead of an actual edge location. In a production environment, users would not use this dummy data submission. Instead, they would configure a service such as AWS IoT SiteWise Edge for their specific application.

Run the python script (inside the project folder in the container) ```python ./source/generate_dashboard_json.py``` which will load the dashboard template and fill in the account specific information. A new dashboard json file ("generated_dashboard.json") will be generated and added to the newly created S3 Bucket (we will use this file during the Grafana setup).

Run the python script (inside the project folder in the container) ```python ./source/generate_twinmaker_scene_json.py``` which will load the dashboard template and fill in the account specific information. A new dashboard json file ("generated_FirstScene.json") will be generated and will be used by the final TwinMaker setup.

Last step will again use CDK but now we will deploy a TwinMaker scene which connects the IoT SiteWise data to the 3D model we uploaded in the previous step.

```
cd TwinMakerSceneStack
cdk synth
cdk deploy
cd ..
```


## Deployment Validation

* Within the AWS Console, open CloudFormation page and verify the status of the template with the name containing FMUCalibrationStack.
* If deployment is successful, you should see an active IoT SiteWise database, new S3 buckets, EventBridge rules, and AWS Batch compute environments. 


## Running the Guidance

1) Once you have completed the infrastructure deployment in the previous section, we will need to run a dummy data population script. We can leverage the container we already built via:

```
docker run -it -v /home/ubuntu/.aws:/root/.aws -v ./:/project --network=host --shm-size=20000000m fmucalibrate /bin/bash  
```
   
   This Docker command will interactively run the container, mounting the AWS credentials and the current directory to the container. In addition, the container will use the same network layout as the host EC2 instance. Once inside the container, you can navigate to the 'project' folder to find the cloned repository.

   The synthetic data generation script is simply uploading data in some increments to simulate IoT data being written to the IoT SiteWise database.

   In production, the user is expected to connect physical sensors to this database and you will _not_ need to run this dummy script during production operation. From within the container:

   ```
   python /project/source/PushSiteWiseData_startBatchPredictions.py
   ```

   In AWS Console, users can navigate to IoT SiteWise and watch the dummy script adding data to the database. 


   </br>
   <center>
   <img src="./assets/images/screenshot_sitewise.PNG" width=600>
   </center>
   </br>

   The default calibration time in the ```iot_config.json``` file is set to every 1min.  For this example, users should wait around 5-10min for the dummy data to be pushed up to SiteWise and for the TwinFlow Unscented Kalman Filter to pull the data, calibrate the digital twin, and push results back to SiteWise.

2) Next we need to setup user access to Grafana to review the data. 
   
   Setup SSO password access:
   In AWS Console, navigate to the "IAM Identity Center".  Create a user that you would like to provide access to the Grafana dashboard.  This user will be able to visually review all of the data we setup in the dashboard and customize the dashboard.

   Connect the user to Grafana:  In the AWS Console, navigate to the Grafana page. Select the newly made Grafana workspace generated by this Guidance. In the authentication tab, add the user we have just created.

   </br>
   <center>
   <img src="./assets/images/screenshot_grafana_users.PNG" width=600>
   </center>
   </br>
   
   For the first user setup, we recommend making them an admin to ensure they can load the data and customize the dashboard.

   </br>
   <center>
   <img src="./assets/images/screenshot_grafana_users_admin.PNG" width=600>
   </center>
   </br>
      
   Enter into Grafana console: Now that we have both created an AWS Managed Grafana and added a user to the workspace, lets enter into Grafana by clicking the workspace URL:

   </br>
   <center>
   <img src="./assets/images/screenshot_grafana_URL.PNG" width=600>
   </center>
   </br>

   The username and password are for the user you created in the IAM Identity Center step.

3) Add a data source in Grafana: Before you can setup dashboards, we need to first connect Grafana to a specific data source. Click Home -> Apps -> AWS Data Sources 


   </br>
   <center>
   <img src="./assets/images/screenshot_grafana_data_sources.PNG" width=600>
   </center>
   </br>

An option for SiteWise should appear, click the install button (install the latest version). Repeat this step for TwinMaker to enable adding 3D assets to the Grafana dashboard. 

   </br>
   <center>
   <img src="./assets/images/screenshot_grafana_sitewise.PNG" width=600>
   </center>
   </br>

Once installation of the plugin is complete, return to the Data Sources, select Sitewise, select your region and add the data source. Repeat this step for TwinMaker. One additional step is needed to complete the connection of Grafana and TwinMaker, which is to insert the "DemoTwinMakerRole" IAM ARN into the data source of the Grafana plugin. The  ```python ./source/generate_dashboard_json.py``` in step 4 will print to screen the text needed to be copied and pasted into Grafana. If you recieve any errors about "assumed roles" it is due likely due to the Grafana plugin not understanding the permissions for the connections. 

4) Generate a dashboard: We can run a dashboard generation script that will generate a yaml file specific to this Guidance example. 
   
   a) At this point we should have run the python script (inside the project folder in the container) ```python ./source/generate_dashboard_json.py``` which will load the dashboard template and fill in the account specific information. A new dashboard json file ("generated_dashboard.json") will be generated.
   <br/>b) The generated json file can be imported directly into Grafana, which will define some panels and plot all of the inputs and results defined in the iot_config.json file.  This enables live review of the L4 calibration and the measured IoT data being ingested in IoT SiteWise. Download the generated json file from the s3 bucket using the console enabling use with Grafana setup. 

   </br>
   <center>
   <img src="./assets/images/screenshot_grafana_dashboard_import.PNG" width=600>
   </center>
   </br>

With the dashboard imported we should see the following combination of phyisical sensors, virtual sensors, calibration coefficients, and TwinMaker 3D models. 

   </br>
   <center>
   <img src="./assets/images/screenshot_grafana_dashboard_final.PNG" width=600>
   </center>
   </br>


## Description of TwinFlow Script

The TwinFlow script, ```fmu_calibrate.py```, that is embedded in the container:

* Pulls data from IoT SiteWise
* Sets up an Unscented Kalman Filter (UKF) in which the transition function is the digital twin
* Runs the UKF in parallel to probabalistically determine the inferred variables within the digital twin
* Uses the UKF inferred variables in the digital twin to make predictions about many unmeasured variabls
* Pushes these predictions (i.e. virtual sensors), the UKF mean value of the inferred variables, and the uncertainty of the inferred variables back into the IoT SiteWise database.

The first step in the script is for TwinFlow to determine the unique metadata information for all assets deployed during the CDK steps.


   </br>
   <center>
   <img src="./assets/images/screenshot_twinflow_metadata.PNG" width=600>
   </center>
   </br>

Next, TwinFlow downloads the data from IoT SiteWise for the variables provided in the ```iot_config.json``` file.  The exact database ID for sitewise was determined in the previous metadata step. The SiteWise database relates timeseries data and attributes based on asset IDs. Using TwinFlow, we can automatically determine what these values are instead of manually trying to figure them out in the AWS Console. The last step of the the ```get_data()``` function is ensuring all pulled data is temporally syncronized.  

   </br>
   <center>
   <img src="./assets/images/screenshot_twinflow_getdata.PNG" width=600>
   </center>
   </br>

With the newly downloaded data, we can combine the Unscented Kalman Filter and the IoT data to calibrate the digital twin.  Users who are customizing this guidance for their own applications will need to experiement and "design" the matrices for the process noise and the measurment noise.  Users should conceptually think of the process noise as the minimum allowable step size for the UKF purturbations and the mesurement noise as coefficient that provides numerically stability but also determines the level of trust in the incoming data.  

If a user is ensure where to start for their application, consider starting the measurment noise with the observed variance in the incoming IoT data. 

TwinFlow utilizes an S3 Bucket to save the current state of the UKF to peristent storage.  Hence, each time a new calibration worker is generated in AWS Batch, TwinFlow will look for an archived file in an S3 bucket to restart the filtering.  

UKF uses "black box" functions for both the transition function and observation function.  TwinFlow UKF is an object with default functions that exhibit a linear assumption.  In this example, we do not overwrite the observation function as a linear assumption is reasonable.  However, we would like to call the digital twin for each transition function execution. Thus, in this example we create our own function that includes any algorithm a user desires.  Here, we include coefficient clips for stability, we use TwinFlow to execute the FMU and return the values back to the UKF. Notice, that this digital twin is run transiently and TwinFlow will determine when convergence has been achieved terminating the simulation.  

   </br>
   <center>
   <img src="./assets/images/screenshot_twinflow_transition_function.PNG" width=600>
   </center>
   </br>
   
After the digital twin has been calibrated by the UKF, the digital twin is used to make predictions serving as a virtual sensor for many unmeasured variables. This step is performed in the ```make_prediction``` function in the TwinFlow script. The variables used for the virtual sensors are defined in the ```iot_config.json``` file. The final step is to again use TwinFlow auto determine the variable names and property/asset IDs in SiteWise and push back up to the database.

Notice that the uncertainty bands are each their own property in SiteWise.  The damping coefficient b2 has a property ID in SiteWise, but in addition, the lower and upper bounds also each have their own property ID.  These are then displayed in Grafana with formatting changes.

## Next Steps

Users can familarize themselves with each of the steps on the guidance and determine how they would like to customize them for their applications.

Key areas to customize for a different application are:

* The digital twin embedded in the containers
* Parameters in the TwinFLow calibration script
* Json inputs


## Clean Up

The solution can be removed from a user's account by either opening up the EC2 instance and navigating back to the CDK directory (TwinMakerSceneStack). Within this directory run the following commands:

```
cd TwinMakerSceneStack
cdk destroy
cd ..
cd FMUCalibrationStack
cdk destroy
```

An alternative is to use the AWS Console.  Navigate to the CloudFormation page and find the FMUCalibrationStack Stack.  Select the delete stack option and the CloudFormation automation will remove all infrastructure deployed specifically in this stack. Depending on the frequency of EventBridge workers in the ```iot_config.json``` file, the CDK may require some help during clean up.  The CDK will wait for all jobs to finish in Batch before terminating EC2 instnaces, however if EventBridge is generating new jobs too quickly, a user may need to manually terminate the EC2 instance, which will allow CDK to terminate Batch.

Any ECR repos created in this guidance need to be manually deleted as a data safety precaution.  These repos will continue to incur costs until deleted. 

## Security 

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.


## License

This library is licensed under the MIT-0 License. See the LICENSE file.
