# Registration Service

Registration Service is a Spring Boot microservice in the SnapGrid project. It manages lab and device metadata for the distributed robotics demo system.

## Responsibilities

- Register labs
- Register devices under a lab
- Query all labs
- Query devices by lab
- Return aggregated lab + device metadata for frontend integration
- Provide metadata validation endpoints for worker services

---

## Role in System Architecture

The registration-service sits between the **frontend** and **worker pipeline**, enabling both data management and validation.

### General Architecture

Client / Frontend
│
▼
Registration Service  ───────────────┐
│                            │
▼                            ▼
In-memory Store               Worker3 (validation)
│
▼
Isaac Sim

---

## Data Flow

### 1. Lab & Device Registration

Frontend → POST /labs  
Frontend → POST /labs/{labId}/devices

→ Data stored in registration-service

---

### 2. Worker Validation Flow

SQS Message → Worker3  
→ Registration Service (GET device)  
→ Valid? → Send to Isaac Sim

---

### 3. Frontend Lookup

Frontend → GET /labs/full

→ Returns full lab + device structure

---

## Tech Stack

- Java 17
- Spring Boot 3.2.5
- Maven
- In-memory store (MVP version)

## Run the Service

From the `registration-service` directory:

```bash
mvn spring-boot:run

---

## How to Run

cd registration-service  
mvn spring-boot:run  

Service runs at:

http://localhost:8084

---

## 📡 API Endpoints

---

### Create Lab

POST /labs  
Content-Type: application/json  

Request:
{
  "labId": "lab-a",
  "name": "Seattle FlexLab",
  "location": "Seattle, WA"
}

Response:
{
  "labId": "lab-a",
  "name": "Seattle FlexLab",
  "location": "Seattle, WA"
}

---

### Get All Labs

GET /labs  

Response:
[
  {
    "labId": "lab-a",
    "name": "Seattle FlexLab",
    "location": "Seattle, WA"
  }
]

---

### Register Device

POST /labs/{labId}/devices  
Content-Type: application/json  

Request:
{
  "deviceId": "panda-arm-1",
  "displayName": "Panda Arm 1",
  "type": "arm",
  "modules": ["kinematics", "collision", "trajectory"],
  "capacity": 2
}

---

### Get Devices by Lab

GET /labs/{labId}/devices  

---

### Get Full Lab + Devices

GET /labs/full  

Response:
[
  {
    "labId": "lab-a",
    "name": "Seattle FlexLab",
    "location": "Seattle, WA",
    "devices": [
      {
        "deviceId": "panda-arm-1",
        "labId": "lab-a",
        "displayName": "Panda Arm 1",
        "type": "arm",
        "modules": ["kinematics", "collision", "trajectory"],
        "capacity": 2,
        "inUse": 0,
        "available": 2
      }
    ]
  }
]

---

### Get Single Device (Worker Validation)

GET /labs/{labId}/devices/{deviceId}

---

## Data Model

### Lab

{
  "labId": "lab-a",
  "name": "Seattle FlexLab",
  "location": "Seattle, WA"
}

---

### Device

{
  "deviceId": "panda-arm-1",
  "labId": "lab-a",
  "displayName": "Panda Arm 1",
  "type": "arm",
  "modules": ["kinematics"],
  "capacity": 2,
  "inUse": 0,
  "available": 2
}

---

## Internal Architecture

Controller → Service → Store

Controller:
- Handles HTTP requests
- Defines API endpoints

Service:
- Business logic
- Validation

Store:
- In-memory storage
- Temporary persistence

---

## Validation Rules

- labId must be unique
- deviceId must be unique within a lab
- capacity must be greater than 0
- lab must exist before adding device

---

## Integration

### Worker3

Uses:
GET /labs/{labId}/devices/{deviceId}

Purpose:
- Validate device existence
- Prevent invalid simulation input

---

### Frontend

Uses:
GET /labs/full

Purpose:
- Render lab + device UI
- Provide selection options

---

## 🧪 Testing (curl)

Create Lab:

curl -X POST http://localhost:8084/labs \
-H "Content-Type: application/json" \
-d '{
  "labId": "lab-a",
  "name": "Seattle FlexLab",
  "location": "Seattle, WA"
}'

---

Create Device:

curl -X POST http://localhost:8084/labs/lab-a/devices \
-H "Content-Type: application/json" \
-d '{
  "deviceId": "panda-arm-1",
  "displayName": "Panda Arm 1",
  "type": "arm",
  "modules": ["kinematics"],
  "capacity": 2
}'
