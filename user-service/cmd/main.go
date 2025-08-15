package main

import (
	"log"
	"net/http"

	"user-service/internal/infrastructure/database"
	"user-service/internal/infrastructure/server"
)

func main() {
	// Initialize repo
	db, err := database.NewPostgresDatabase()
	if err != nil {
		log.Fatalf("Failed to connect to repo: %v", err)
	}

	// Initialize server
	srv := server.NewUserServer(db)

	log.Println("Starting User Service on :8082")
	if err := http.ListenAndServe(":8082", srv.Routes()); err != nil {
		log.Fatalf("Server failed to start: %v", err)
	}
}
