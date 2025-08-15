package main

import (
	"log"
	"net/http"
	"os"

	"github.com/joho/godotenv"
	"go.uber.org/zap"

	"auth-service/internal/repo"
	"auth-service/internal/server"
)

func main() {
	if err := godotenv.Load(); err != nil {
		log.Println(".env file not found, using environment variables")
	}

	logger, err := zap.NewProduction()
	if err != nil {
		log.Fatalf("Failed to initialize logger: %v", err)
	}
	defer logger.Sync()

	db, err := repo.NewPostgresDatabase(logger)
	if err != nil {
		logger.Fatal("Failed to connect to database", zap.Error(err))
	}

	jwtSecret := os.Getenv("JWT_SECRET")
	if jwtSecret == "" {
		logger.Fatal("JWT_SECRET is not set")
	}

	authServer := server.NewAuthServer(db, jwtSecret, logger)

	logger.Info("Starting Authentication Service on :8081")
	if err := http.ListenAndServe(":8081", authServer.Routes()); err != nil {
		logger.Fatal("Server failed to start", zap.Error(err))
	}
}
