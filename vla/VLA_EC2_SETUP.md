# VLA Inference — Setup & Training Guide

This document covers the full VLA pipeline for SnapGrid: fine-tuning OpenVLA-7b on BridgeData V2 block-pushing data using a university HPC cluster, then running inference wired to the SQS pipeline.

---

## Architecture

```
Isaac Sim (Windows, RTX 5090)
    ↓ /camera endpoint (JPEG frame)
VLA Inference Node (HPC cluster or EC2 g4dn.xlarge)
    - pulls camera frame via HTTP
    - runs fine-tuned OpenVLA-7b inference
    - publishes joint angles → SQS roboparam-queue
    ↓
worker3 (Spring Boot, Mac) → Isaac Sim REST → arm executes
    ↓
Redis → aggregator → WebSocket → frontend
```

---

## VLA Strategy

**Model:** OpenVLA-7b (HuggingFace: `openvla/openvla-7b`)

**Approach:** Fine-tune on BridgeData V2 block-pushing subset rather than zero-shot inference. Fine-tuning on open-source manipulation data produces noticeably more purposeful arm behavior and supports a stronger research narrative around sim-to-real transfer characteristics.

**Narrative framing:** *"We fine-tuned OpenVLA on the BridgeData V2 block-pushing subset and evaluate sim-to-real transfer into NVIDIA Isaac Sim. The VLA model is a pluggable research-grade component sitting on top of our distributed infrastructure layer."*

---

## Phase 1: Fine-tuning on HPC Cluster

### Dataset: BridgeData V2 (block-pushing subset)

BridgeData V2 is an open-source robot manipulation dataset collected on a WidowX arm. The block-pushing subset contains demonstrations of pushing colored blocks on a tabletop — directly analogous to the SnapGrid Isaac Sim scene.

Download the subset:
```bash
# On HPC cluster
pip install huggingface_hub
python -c "
import huggingface_hub
huggingface_hub.snapshot_download(
    'rail-berkeley/bridge_dataset',
    repo_type='dataset',
    local_dir='./bridge_data',
    allow_patterns=['*block*']
)
"
```

### HPC Job Script (SLURM)

Save as `vla/hpc_finetune.sh`:

```bash
#!/bin/bash
#SBATCH --job-name=openvla-finetune
#SBATCH --gres=gpu:1
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=logs/finetune_%j.out

module load python/3.10
module load cuda/11.8

pip install transformers==4.41.2 tokenizers==0.19.1 accelerate==0.30.1 \
    bitsandbytes==0.43.1 pillow boto3 timm==0.9.16 peft -q

python vla/finetune.py \
    --model_id openvla/openvla-7b \
    --dataset_path ./bridge_data \
    --output_dir ./vla/checkpoints \
    --num_epochs 3 \
    --batch_size 4 \
    --learning_rate 2e-5
```

Submit:
```bash
sbatch vla/hpc_finetune.sh
```

### Expected Training Time
- ~2-3 hours on a single A100 or V100 GPU
- ~4-6 hours on older HPC GPUs (P100, RTX 3090)

### Download Weights After Training

```bash
# From your Mac, pull the fine-tuned checkpoint
scp -r <hpc-username>@<hpc-address>:~/vla/checkpoints ./vla/checkpoints
```

---

## Phase 2: Inference Wired to SQS

### Inference Script: `vla/infer.py`

The inference loop:
1. Pull a camera frame from Isaac Sim (`GET http://<windows-ip>:8011/camera`)
2. Run fine-tuned OpenVLA inference with instruction prompt
3. Parse 7-DOF joint angle output
4. Clamp joint angles to safe Franka Panda ranges
5. Publish to SQS `roboparam-queue`
6. worker3 picks up → forwards to Isaac Sim → arm executes

### Instruction Prompt

```python
INSTRUCTION = "push the red block forward on the table"
```

### Joint Angle Safety Clamping

OpenVLA outputs may exceed safe joint limits. Always clamp before publishing to SQS:

```python
JOINT_LIMITS = [
    (-2.8973, 2.8973),   # joint 1
    (-1.7628, 1.7628),   # joint 2
    (-2.8973, 2.8973),   # joint 3
    (-3.0718, -0.0698),  # joint 4
    (-2.8973, 2.8973),   # joint 5
    (-0.0175, 3.7525),   # joint 6
    (-2.8973, 2.8973),   # joint 7
]
```

---

## Phase 3: AWS EC2 (when quota approved)

For sustained inference during the showcase, migrate from HPC to EC2.

### AWS Resources

| Resource | Name / ID | Notes |
|---|---|---|
| EC2 instance type | `g4dn.xlarge` | 1x T4 GPU, 16GB VRAM |
| AMI | `ami-0c02fb55956c7d316` | Amazon Linux 2, us-east-1 |
| Key pair | `openvla-key` | Stored at `/Users/carolina1650/CS6650/openvla-key.pem` |
| Security group | `sg-04e3d077c5be1f4fd` (openvla-sg) | SSH port 22 open to static IP only |
| Region | `us-east-1` | Same region as SQS queue |
| vCPU quota request | L-DB2E81BA | Requested 4 vCPUs, status PENDING |

### Launch Instance (once quota approved)

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

### SSH

```bash
ssh -i /Users/carolina1650/CS6650/openvla-key.pem ec2-user@<public-ip>
```

### Cost Estimate

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

## Milestone Checklist

- [ ] Download BridgeData V2 block-pushing subset on HPC
- [ ] Run fine-tuning job on HPC (`hpc_finetune.sh`)
- [ ] Download checkpoint to Mac (`vla/checkpoints/`)
- [ ] Add `/camera` endpoint to `isaac-sim/sim_state.py`
- [ ] Write `vla/infer.py` inference + SQS publish loop
- [ ] Test full pipeline: camera → OpenVLA → SQS → worker3 → Isaac Sim
- [ ] Collect latency numbers for showcase
- [ ] Migrate inference to EC2 (when quota approved)