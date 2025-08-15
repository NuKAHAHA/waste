FROM golang:1.22-alpine AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN CGO_ENABLED=0 GOOS=linux go build -o /auth-service ./cmd/main.go

FROM alpine:latest

WORKDIR /root/

COPY --from=builder /auth-service .
COPY .env .

EXPOSE 8081

CMD ["./auth-service"]