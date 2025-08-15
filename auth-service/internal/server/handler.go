package server

import (
	"encoding/json"
	"net/http"

	"go.uber.org/zap"

	"auth-service/internal/model"
)

type registerRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
	Role     string `json:"role"`
}

type loginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

func (s *AuthServer) handleRegister(w http.ResponseWriter, r *http.Request) {
	var req registerRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.logger.Error("Invalid register request body", zap.Error(err))
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	user, err := s.authService.Register(req.Email, req.Password, model.UserRole(req.Role))
	if err != nil {
		s.logger.Error("Registration failed", zap.Error(err), zap.String("email", req.Email))
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(user); err != nil {
		s.logger.Error("Failed to encode register response", zap.Error(err))
	}
}

func (s *AuthServer) handleLogin(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.logger.Error("Invalid login request body", zap.Error(err))
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	token, err := s.authService.Login(req.Email, req.Password)
	if err != nil {
		s.logger.Error("Login failed", zap.Error(err), zap.String("email", req.Email))
		http.Error(w, err.Error(), http.StatusUnauthorized)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(map[string]string{"token": token}); err != nil {
		s.logger.Error("Failed to encode login response", zap.Error(err))
	}
}

func (s *AuthServer) handleValidateToken(w http.ResponseWriter, r *http.Request) {
	tokenString := r.Header.Get("Authorization")
	if tokenString == "" {
		s.logger.Info("Missing token in validate request")
		http.Error(w, "Missing token", http.StatusBadRequest)
		return
	}

	user, err := s.authService.ValidateToken(tokenString)
	if err != nil {
		s.logger.Error("Token validation failed", zap.Error(err))
		http.Error(w, err.Error(), http.StatusUnauthorized)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(user); err != nil {
		s.logger.Error("Failed to encode validate response", zap.Error(err))
	}
}
