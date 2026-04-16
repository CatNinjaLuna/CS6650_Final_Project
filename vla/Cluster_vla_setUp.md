# VLA Fine-Tuning — Northeastern Discovery Cluster Setup

This document covers the HPC cluster setup for fine-tuning OpenVLA-7b on Isaac Sim demonstration data using LoRA, as part of the SnapGrid distributed robotics pipeline.

---

## Cluster Info

| Property | Value |
|---|---|
| Cluster | Northeastern University Discovery Cluster |
| Partition | `gpu-interactive` |
| GPU | NVIDIA A100-SXM4-80GB |
| Session type | Interactive (2hr) / SLURM batch |
| Working directory | `/projects/SuperResolutionData/CL-shadowRemoval-logChroma/vla-inference` |

---

## Environment Setup

### Create and activate the conda environment

```bash
conda create -n openvla python=3.10 -y
conda activate openvla
```

### Install dependencies

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
pip install transformers==4.41.2 tokenizers==0.19.1 accelerate==0.30.1 \
    bitsandbytes==0.43.1 pillow boto3 timm==0.9.16 peft huggingface_hub
```

### Verify installation

```bash
python -c "
import torch
import transformers
print('torch:', torch.__version__)
print('cuda:', torch.cuda.is_available())
print('transformers:', transformers.__version__)
print('GPU:', torch.cuda.get_device_name(0))
"
```

Expected output:
```
torch: 2.7.1+cu118
cuda: True
transformers: 4.41.2
GPU: NVIDIA A100-SXM4-80GB
```

---

## Model Download

Download OpenVLA-7b weights from HuggingFace (~15GB):

```bash
cd /projects/SuperResolutionData/CL-shadowRemoval-logChroma/vla-inference

python -c "
import huggingface_hub
huggingface_hub.snapshot_download(
    'openvla/openvla-7b',
    local_dir='./openvla-7b',
    ignore_patterns=['*.msgpack', '*.h5']
)
print('Download complete')
"
```

---

## Fine-Tuning Strategy: LoRA on Isaac Sim Demos

### Why not BridgeData V2?

OpenVLA-7b was already pretrained on a superset of datasets that includes BridgeData V2. Fine-tuning on BridgeData V2 again would yield ~100% action accuracy on that data but would not improve performance for our specific Isaac Sim scene — it would just be re-learning what the model already knows.

### Why LoRA?

LoRA (Low-Rank Adaptation) freezes the original 7B model weights and adds small trainable adapter matrices (~50M parameters). This means:
- Full fine-tuning: update all 7B parameters → needs multiple GPUs, days of training
- LoRA fine-tuning: update ~50M adapter parameters → runs on a single A100 in 2-3 hours

For adapting OpenVLA to a new scene and task, LoRA is the right call — sufficient quality, dramatically lower cost.

### Dataset: Isaac Sim Demonstrations

Collect ~50-100 demo trajectories directly from Isaac Sim:
- Camera image from `/camera` endpoint
- Natural language instruction (e.g. `"push the red block forward"`)
- 7-DOF joint angles at each step

Convert to RLDS format (required by OpenVLA fine-tuning scripts) using the tools in the OpenVLA repo.

### Clone the Official OpenVLA Repo

```bash
cd /projects/SuperResolutionData/CL-shadowRemoval-logChroma/vla-inference
git clone https://github.com/openvla/openvla.git
cd openvla
pip install -e .
```

### LoRA Fine-Tuning Script

```bash
cd /projects/SuperResolutionData/CL-shadowRemoval-logChroma/vla-inference/openvla

torchrun --standalone --nnodes=1 --nproc-per-node=1 vla-scripts/finetune.py \
    --vla_path ../openvla-7b \
    --data_root_dir ../isaac_demos \
    --dataset_name snapgrid_push \
    --run_root_dir ../checkpoints \
    --use_lora True \
    --lora_rank 32 \
    --batch_size 16 \
    --grad_accumulation_steps 1 \
    --learning_rate 5e-4 \
    --image_aug True \
    --wandb_project snapgrid-vla \
    --wandb_entity <your-wandb-username>
```

### SLURM Batch Script

Save as `vla/hpc_finetune.sh`:

```bash
#!/bin/bash
#SBATCH --job-name=openvla-lora
#SBATCH --partition=gpu
#SBATCH --gres=gpu:a100:1
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=logs/finetune_%j.out

conda activate openvla
cd /projects/SuperResolutionData/CL-shadowRemoval-logChroma/vla-inference/openvla

torchrun --standalone --nnodes=1 --nproc-per-node=1 vla-scripts/finetune.py \
    --vla_path ../openvla-7b \
    --data_root_dir ../isaac_demos \
    --dataset_name snapgrid_push \
    --run_root_dir ../checkpoints \
    --use_lora True \
    --lora_rank 32 \
    --batch_size 16 \
    --learning_rate 5e-4 \
    --image_aug True
```

Submit:
```bash
sbatch vla/hpc_finetune.sh
```

Monitor:
```bash
squeue -u $USER
tail -f logs/finetune_<job_id>.out
```

### Expected Training Time on A100-80GB
- ~2-3 hours for 50-100 Isaac Sim demo trajectories with LoRA

---

## After Training: Transfer Weights to Mac

```bash
# From your Mac terminal
scp -r li.yuhan5@login.discovery.neu.edu:/projects/SuperResolutionData/CL-shadowRemoval-logChroma/vla-inference/checkpoints ~/CS6650/CS6650_Final_Project/vla/checkpoints
```

---

## Directory Structure

```
vla-inference/
├── openvla-7b/          # pretrained model weights (~15GB)
├── openvla/             # official OpenVLA repo (fine-tuning scripts)
├── isaac_demos/         # collected Isaac Sim demo trajectories (RLDS format)
├── checkpoints/         # LoRA fine-tuned adapter weights
└── logs/                # SLURM job logs
```

---

## End-to-End VLA Pipeline (April 21 Target)

The existing scene (Franka Panda + red/green blocks) is used as-is. OpenVLA replaces the hardcoded `push_red`/`push_green` action shortcuts with real model inference:

**Current flow (hardcoded):**
```
User clicks button → "push_red" → SQS → worker3 → Isaac Sim
```

**VLA flow (target):**
```
Isaac Sim camera image + text instruction → OpenVLA → 7 joint angles → SQS → worker3 → Isaac Sim → arm moves
```

### Step 1 — Add `/camera` endpoint to `sim_state.py` (~30 min)
Returns a JPEG frame from the Isaac Sim scene camera. This is the visual observation fed into OpenVLA.

### Step 2 — Write `vla/infer.py` (~1-2 hrs)
Inference loop:
1. `GET http://192.168.1.3:8011/camera` → JPEG frame
2. Send image + instruction (`"push the red block forward"`) to OpenVLA
3. Receive 7-DOF joint angles
4. Clamp to safe Franka joint limits
5. Publish to SQS `roboparam-queue`
6. worker3 picks up → Isaac Sim executes → arm moves

### Step 3 — Transfer LoRA checkpoint to inference node
Download from HPC cluster to Mac or EC2 once fine-tuning is complete.

### Step 4 — Demo stabilization
- Tune instruction prompt wording
- Verify joint angle output is in safe range
- Record clean end-to-end demo video as backup

### Step 5 — Collect latency numbers
Instrument the full pipeline: camera pull → inference → SQS publish → worker3 → Isaac Sim response. Surface these numbers in the frontend and showcase presentation.

---

## Future Work — Key-Grid Puzzle Scene

A more complex VLA task planned as a research extension:

**Scenario:** A mobile robot navigates a 2D grid with:
- **Black blocks** as obstacles (can be avoided or pushed)
- **A key** the robot must pick up
- **A door** at a target grid coordinate — only reachable with the key
- **Efficiency metric** — fewer steps to solve = higher score

**Why this is compelling:** Requires language-grounded planning (understand "pick up key before going to door"), obstacle reasoning, and tool use — a significant step beyond single-object manipulation.

**Planned stack:**
- Isaac Sim for physics and rendering (top-down camera view)
- VLA for high-level action token decisions (`move_up`, `pick_key`, `push_block`, `open_door`)
- Scripted motion primitives for reliable low-level execution
- Same SQS → worker3 → Isaac Sim distributed pipeline

**Prerequisite:** Collect grid puzzle demonstration data, convert to RLDS format, LoRA fine-tune OpenVLA on task-specific behavior.