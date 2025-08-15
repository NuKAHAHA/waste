package server

import (
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/cors"
	"go.uber.org/zap"

	"auth-service/internal/model"
	"auth-service/internal/repo"
	"auth-service/internal/service"
)

type AuthServer struct {
	router      *chi.Mux
	authService model.AuthService
	logger      *zap.Logger
}

func NewAuthServer(db *repo.PostgresDatabase, jwtSecret string, logger *zap.Logger) *AuthServer {
	authService := service.NewAuthService(db, jwtSecret, logger)

	server := &AuthServer{
		router:      chi.NewRouter(),
		authService: authService,
		logger:      logger,
	}

	server.setupRoutes()
	return server
}

func (s *AuthServer) setupRoutes() {
	s.router.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{"*"},
		AllowedMethods:   []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type", "X-CSRF-Token"},
		ExposedHeaders:   []string{"Link"},
		AllowCredentials: false,
		MaxAge:           300,
	}))

	s.router.Post("/register", s.handleRegister)
	s.router.Post("/login", s.handleLogin)
	s.router.Post("/validate", s.handleValidateToken)
}

func (s *AuthServer) Routes() *chi.Mux {
	return s.router
}
