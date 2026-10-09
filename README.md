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

## Scientific research module — Assignment 3

[Smart Waste Astana](research/smart-waste-astana/README.md) is an independent Python research module with two/five explainable agents, synthetic Astana telemetry, offline HTML/CSV/JSON results, 30 automated tests and verified ZIP delivery. It runs without third-party runtime dependencies:

```bash
cd research/smart-waste-astana
python main.py demo
python -m unittest discover -s tests -v
```

[Analytical report](research/smart-waste-astana/docs/report/Assignment_3_Smart_Waste_Report_RU.pdf) · [Editable report](research/smart-waste-astana/docs/report/Assignment_3_Smart_Waste_Report_RU.docx) · [CI/CD](.github/workflows/smart-waste-ci.yml) · [Validation](research/smart-waste-astana/docs/validation.md)
