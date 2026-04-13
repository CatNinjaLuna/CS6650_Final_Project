# VLA Inference — AWS EC2 Setup

This document covers the AWS EC2 setup for running OpenVLA inference as part of the SnapGrid distributed robotics pipeline.

---

## Architecture

```
Isaac Sim (Windows, RTX 5090)
    ↓ /camera endpoint (JPEG frame)
EC2 g4dn.xlarge (us-east-1)
    - pulls camera frame via HTTP
    - runs OpenVLA-7b inference (4-bit quantized)
    - publishes joint angles → SQS roboparam-queue
    ↓
worker3 (Spring Boot, Mac) → Isaac Sim REST → arm executes
    ↓
Redis → aggregator → WebSocket → frontend
```

---

## AWS Resources Created

| Resource | Name / ID | Notes |
|---|---|---|
| EC2 instance type | `g4dn.xlarge` | 1x T4 GPU, 16GB VRAM |
| AMI | `ami-0c02fb55956c7d316` | Amazon Linux 2, us-east-1 |
| Key pair | `openvla-key` | Stored at `/Users/carolina1650/CS6650/openvla-key.pem` |
| Security group | `sg-04e3d077c5be1f4fd` (openvla-sg) | SSH port 22 open to static IP only |
| Region | `us-east-1` | Same region as SQS queue |
| vCPU quota request | L-DB2E81BA | Requested 4 vCPUs, status PENDING |

---

## Prerequisites

- AWS CLI configured with `snapgrid-worker` credentials
- IAM policies attached to `snapgrid-worker`: `AmazonEC2FullAccess`, `AmazonSQSFullAccess`, `ServiceQuotasFullAccess`
- vCPU quota for G instances approved (request ID: `60c7a04386b44e029b6f5c7cbfd5cecamAt29KL0`)

---

## Launching the Instance

Once the vCPU quota is approved, launch with:

```bash
aws ec2 run-instances \
  --image-id ami-0c02fb55956c7d316 \
  --instance-type g4dn.xlarge \
  --key-name openvla-key \
  --security-group-ids sg-04e3d077c5be1f4fd \
  --region us-east-1 \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":100}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=openvla-inference}]' \
  --no-cli-pager
```

Get the public IP:

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=openvla-inference" \
  --query 'Reservations[*].Instances[*].PublicIpAddress' \
  --output text
```

---

## SSH into the Instance

```bash
ssh -i /Users/carolina1650/CS6650/openvla-key.pem ec2-user@<public-ip>
```

---

## Instance Setup (first time)

```bash
# Update and install dependencies
sudo yum update -y
sudo yum install -y python3-pip git

# Install PyTorch with CUDA
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# Install OpenVLA and inference dependencies
pip3 install transformers accelerate bitsandbytes pillow boto3

# Clone the repo
git clone https://github.com/CatNinjaLuna/CS6650_Final_Project.git
cd CS6650_Final_Project
```

---

## OpenVLA Inference Script

The inference script (`vla/infer.py`) does the following loop:

1. Pull a camera frame from Isaac Sim (`GET http://<windows-ip>:8011/camera`)
2. Run OpenVLA-7b inference with a natural language instruction
3. Parse the 7-DOF joint angle output
4. Publish to SQS `roboparam-queue`
5. worker3 picks up → forwards to Isaac Sim → arm executes

---

## Cost Estimate

| Resource | Rate | Est. usage | Est. cost |
|---|---|---|---|
| g4dn.xlarge | $0.526/hr | ~20 hrs total | ~$10.50 |
| EBS 100GB gp2 | $0.10/GB/mo | 1 month | $10.00 |
| SQS messages | $0.40/1M | negligible | ~$0.00 |
| **Total** | | | **~$20** |

**Always stop the instance when not in use:**

```bash
aws ec2 stop-instances --instance-ids <instance-id>
```

---

## Stopping / Terminating

```bash
# Stop (preserves EBS, can restart)
aws ec2 stop-instances --instance-ids <instance-id>

# Terminate (deletes everything)
aws ec2 terminate-instances --instance-ids <instance-id>
```

---

## Fallback: Google Colab

While the vCPU quota request is pending, OpenVLA inference can be run on Google Colab (T4 GPU, free tier) and wired to the same SQS queue. See `vla/colab_infer.ipynb` for the notebook.