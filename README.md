## Self-Calibrating Level 4 Digital Twins with TwinFlow


# Instructions:


1) Download and install the latest twinflow code: <br>     
```
git clone --recursive https://github.com/aws-samples/twinflow
pip install twinflow/twinstat/dist/*.whl
pip install twinflow/twinmodules/dist/*.whl
pip install twinflow/twingraph/dist/*.whl
```
2) Build and push containers to ECR

The example container ```Dockerfile-fmu-calibrater``` includes both building and installation of TwinFlow and embedding the example digital twin.  This digital twin is in the form of an FMU for this example.

If you are running on an EC2 instance in the cloud, you can use the small twinmodules cli to quickly build and push to your accounts AWS ECR. For example: <br>
```
alias tfcli="python <path to twinflow>/twinmodules/twinmodules/tfcli.py"
tfcli -bp --region us-east-1 -t fmu-calibrate -d ./Dockerfile-fmu-calibrater
```

3) Review the user defined options in the ```iot_config.json```.  Note this file contains cloud specific configuration that need to be set based on your account configuration.  Such as the address for your container images, the account region, s3 bucket names, etc.  This file also includes the specific inputs and outputs for the FMU file that will need to be customized to your application.  You can also control numerical configuration for running the FMU such as step stize, solution converge tolerance, number of iterations to wait for convergence, etc. 

3) Install and deploy CDK IaC

Next we need to install some other tools that enable use for CDK deployments.

Install aws cli:

```
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```
Install npm:
```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.37.2/install.sh | bash
. ~/.nvm/nvm.sh
nvm install node
node -v
npm -v
```
Install cdk cli:
```
npm install -g aws-cdk
```

Install CDK Python packages:
```
pip install aws-cdk-lib
pip install aws-cdk.aws-batch-alpha
```

Deploy entire infrastructure:

```
cd FMUCalibrationStack
cdk bootstrap
cdk synth
cdk deploy
cd ..
```

4) Run sitewise dummy data worker script to simulate data being added to sitewise 

```
   python PushSiteWiseData_startBatchPredictions.py
```

5) Next we need to setup user access to Grafana to review the data. 
   Setup SSO password access. 
   In Grafana setup user authentication and add the user we created.
   Enter into Grafana console
6) Generate a dashboard. Run the python script "generate_dashboard_json.py" which will load the 
   dashboard template and fill in the account specific information. A new dashboard
   json file will be generated.  The generated json file can be imported directly into Grafana,
   which will define some panels and plot all of the inputs and results defined in the 
   iot_config.json file.  This enables live review of the L4 calibration and the measured
   IoT data being ingested in IoT SiteWise. 

## Security 

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.


## License

This library is licensed under the MIT-0 License. See the LICENSE file.
