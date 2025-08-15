# Waste Management Microservices

## Overview
Waste management application for IBM TechXchange 2025 Pre-conference watsonx Hackathon.

## Project Structure
- Microservices architecture
- Clean Architecture principles
- Golang implementation

## Services
1. API Gateway
2. Authentication Service
3. User Service
4. Map Service
5. Schedule Service
6. Waste Classification Service
7. Rating Service
8. Notification Service
9. File Storage Service

## Setup
```bash
# Clone repository
git clone https://github.com/your-org/waste-management

# Initialize modules
go work init

# Build and run services
docker-compose up --build
```

## Technologies
- Go
- gRPC
- PostgreSQL
- Redis
- Kubernetes
- Prometheus
- Jaeger