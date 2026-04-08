# Registration Service

Registration Service is a Spring Boot microservice in the SnapGrid project. It manages lab and device metadata for the distributed robotics demo system.

## Responsibilities

- Register labs
- Register devices under a lab
- Query all labs
- Query devices by lab
- Return aggregated lab + device metadata for frontend integration
- Provide metadata validation endpoints for worker services

## Tech Stack

- Java 17
- Spring Boot 3.2.5
- Maven
- In-memory store (MVP version)

## Run the Service

From the `registration-service` directory:

```bash
mvn spring-boot:run