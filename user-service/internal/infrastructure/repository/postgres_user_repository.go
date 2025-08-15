package repository

import (
  "gorm.io/gorm"
  "github.com/google/uuid"
  "github.com/ibm-techxchange/waste-management/user-service/internal/domain"
)

type PostgresUserRepository struct {
  db *gorm.DB
}

func NewPostgresUserRepository(db *gorm.DB) domain.UserRepository {
  return &PostgresUserRepository{db: db}
}

func (r *PostgresUserRepository) Create(user *domain.User) error {
  return r.db.Create(user).Error
}

func (r *PostgresUserRepository) FindByEmail(email string) (*domain.User, error) {
  var user domain.User
  err := r.db.Where("email = ?", email).First(&user).Error
  return &user, err
}

func (r *PostgresUserRepository) Update(user *domain.User) error {
  return r.db.Save(user).Error
}

func (r *PostgresUserRepository) GetUserActions(userID uuid.UUID) ([]domain.UserAction, error) {
  var actions []domain.UserAction
  err := r.db.Where("user_id = ?", userID).Find(&actions).Error
  return actions, err
}

func (r *PostgresUserRepository) RecordUserAction(action *domain.UserAction) error {
  return r.db.Create(action).Error
}
  