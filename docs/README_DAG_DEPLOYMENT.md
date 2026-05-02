# DAG Deployment Script for CHG0159376

## Quick Start

```bash
# Navigate to au_sre directory
cd /home/bobbygblair/repos/devtools-scripts/au-silver/astutl_python/au_sre

# Load AWS credentials
source .env.prod

# Run deployment script
./deploy_dags_to_prod.sh
```

## What It Does

1. Clones `assist-data-data-pipeline-dags` repository
2. Checks out release branch `release/DATA_1.5.4.0_DME`
3. Verifies DAG files exist
4. Copies DAGs to S3:
   - `data_delivery_dag_weekly.py`
   - `data_delivery_dag_monthly.py`
5. Verifies files in S3
6. Shows cleanup command

## Files

- **deploy_dags_to_prod.sh** - Main deployment script
- **.env.prod** - AWS credentials (NOT committed to git)
- **.env.prod.template** - Template for credentials

## Security

⚠️ The `.env.prod` file contains production AWS credentials and is **excluded from git** via `.gitignore`.

## DAG Changes in This Release

- **STTM changes:** AAS_OSO_STAFFING_DTLS, AAS_OSO_HUMAN_CAP_ASST_EMP
- **Schedule change:** AAS_OSO_TK_FINDB (Monthly → Weekly Sunday 6 AM)

## Post-Deployment Verification

1. Open Airflow UI: https://airflow.prod.assist.mcaas.fcs.gsa.gov
2. Verify all DAGs are visible and enabled
3. Check DataDog for job status:
   ```
   kube_namespace:data-pipeline kube_cluster_name:assist-core-production "DATA_JOB_STATUS:SUCCESS"
   ```
4. Take screenshots of Airflow UI for validation

## Troubleshooting

**AWS credentials not working?**
```bash
# Verify credentials are loaded
echo $AWS_ACCESS_KEY_ID
echo $AWS_SECRET_ACCESS_KEY

# Test AWS access
aws s3 ls s3://assist-core-production-s3/airflow-dags/ --region us-east-1
```

**Git clone fails?**
- Ensure SSH key is configured for github.helix.gsa.gov
- Test: `ssh -T git@github.helix.gsa.gov`

**DAG files not found?**
- Verify branch name: `release/DATA_1.5.4.0_DME`
- Check repository has been updated with latest changes
