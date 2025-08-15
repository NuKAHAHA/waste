package usecase

import (
	"errors"
	"time"

	"github.com/google/uuid"

	"user-service/internal/domain"
)

type UserServiceImpl struct {
	repo domain.UserRepository
}

func NewUserService(repo domain.UserRepository) domain.UserService {
	return &UserServiceImpl{repo: repo}
}

func (s *UserServiceImpl) CreateUser(user *domain.User) error {
	if user.Email == "" {
		return errors.New("email is required")
	}

	user.ID = uuid.New()
	user.CreatedAt = time.Now()
	user.UpdatedAt = time.Now()

	return s.repo.Create(user)
}

func (s *UserServiceImpl) GetUserProfile(userID uuid.UUID) (*domain.User, error) {
	return s.repo.FindByEmail(userID.String())
}

func (s *UserServiceImpl) UpdateUserProfile(user *domain.User) error {
	user.UpdatedAt = time.Now()
	return s.repo.Update(user)
}

func (s *UserServiceImpl) GetUserActionHistory(userID uuid.UUID) ([]domain.UserAction, error) {
	return s.repo.GetUserActions(userID)
}
