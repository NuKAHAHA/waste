package main

import (
	"log"
	"net/http"

	"github.com/ibm-techxchange/waste-management/api-gateway/internal/infrastructure"
	"github.com/ibm-techxchange/waste-management/auth-service/internal/service"
)

func main() {
	// Здесь ты создаёшь сервис авторизации
	// Это пример, в реальности ты можешь подставить нужную инициализацию
	authService := &service.AuthServiceImpl{}

	router := infrastructure.SetupRouter(authService)

	log.Println("API Gateway starting on :8080")
	if err := http.ListenAndServe(":8080", router); err != nil {
		log.Fatalf("Server startup failed: %v", err)
	}
}
