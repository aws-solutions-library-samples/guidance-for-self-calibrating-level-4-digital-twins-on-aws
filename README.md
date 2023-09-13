## Self-Calibrating Level 4 Digital Twins with TwinFlow


# Instructions:


1) Install twinflow python packges: <br>
     https://github.com/aws-samples/twinflow
2) Build and push containers to ECR

You can use the twinmodules cli to quickly build and push to AWS ECR python, for example: <br>
```tfcli.py -bp --region us-east-1 -t twinflow -d ./Dockerfile-twinflow```

3) Install and deploy CDK IaC

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

4) Run sitewise dummy data worker script to simulate data being added to sitewise and initiate the always on DT prediction worker 

```
   python PushSiteWiseData_startBatchPredictions.py
```

5) Next we need to setup user access to Grafana to review the data. 
   Setup SSO password access. 
   In Grafana setup user authentication and add the user we created.
   Enter into Grafana console
6) Generate a dashboard. Run the python script "XYZ.py" which will load the 
   dashboard template and fill in the account specific information. A new dashboard
   json file will be generated.  The generated json file can be imported directly into Grafana,
   which will define some panels and plot all of the inputs and results defined in the 
   iot_config.json file.  This enables live review of the L4 calibration and the measured
   IoT data being ingested in IoT SiteWise. 

## Security 

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.


## License

This library is licensed under the MIT-0 License. See the LICENSE file.
