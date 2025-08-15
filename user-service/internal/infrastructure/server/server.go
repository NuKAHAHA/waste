package server

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"gorm.io/gorm"

	"user-service/internal/domain"
	"user-service/internal/infrastructure/repository"
	"user-service/internal/usecase"
)

type UserServer struct {
	Router      *chi.Mux
	UserService domain.UserService
}

func NewUserServer(db *gorm.DB) *UserServer {
	userRepo := repository.NewPostgresUserRepository(db)
	userService := usecase.NewUserService(userRepo)

	srv := &UserServer{
		Router:      chi.NewRouter(),
		UserService: userService,
	}

	srv.setupRoutes()
	return srv
}

func (s *UserServer) setupRoutes() {
	s.Router.Post("/users", s.createUser)
	s.Router.Get("/users/{id}", s.getUserProfile)
	s.Router.Put("/users/{id}", s.updateUserProfile)
	s.Router.Get("/users/{id}/actions", s.getUserActions)
}

func (s *UserServer) Routes() http.Handler {
	return s.Router
}

func (s *UserServer) createUser(w http.ResponseWriter, r *http.Request) {
	var user domain.User
	if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	if err := s.UserService.CreateUser(&user); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(user)
}

func (s *UserServer) getUserProfile(w http.ResponseWriter, r *http.Request) {
	userID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		http.Error(w, "Invalid user ID", http.StatusBadRequest)
		return
	}

	user, err := s.UserService.GetUserProfile(userID)
	if err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}

	json.NewEncoder(w).Encode(user)
}

func (s *UserServer) updateUserProfile(w http.ResponseWriter, r *http.Request) {
	userID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		http.Error(w, "Invalid user ID", http.StatusBadRequest)
		return
	}

	var user domain.User
	if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	user.ID = userID
	if err := s.UserService.UpdateUserProfile(&user); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	json.NewEncoder(w).Encode(user)
}

func (s *UserServer) getUserActions(w http.ResponseWriter, r *http.Request) {
	userID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		http.Error(w, "Invalid user ID", http.StatusBadRequest)
		return
	}

	actions, err := s.UserService.GetUserActionHistory(userID)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	json.NewEncoder(w).Encode(actions)
}
