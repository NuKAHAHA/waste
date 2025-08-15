package domain

import (
  "time"
  "github.com/google/uuid"
)

type UserRole string

const (
  RoleUser     UserRole = "user"
  RoleAdmin    UserRole = "admin"
  RoleCollector UserRole = "collector"
)

type User struct {
  ID        uuid.UUID `json:"id" gorm:"type:uuid;primary_key"`
  Email     string    `json:"email" gorm:"unique;not null"`
  Name      string    `json:"name"`
  Address   string    `json:"address"`
  Role      UserRole  `json:"role"`
  CreatedAt time.Time `json:"created_at"`
  UpdatedAt time.Time `json:"updated_at"`
}

type UserAction struct {
  ID        uuid.UUID `json:"id" gorm:"type:uuid;primary_key"`
  UserID    uuid.UUID `json:"user_id"`
  Action    string    `json:"action"`
  Details   string    `json:"details"`
  CreatedAt time.Time `json:"created_at"`
}

type UserRepository interface {
  Create(user *User) error
  FindByEmail(email string) (*User, error)
  Update(user *User) error
  GetUserActions(userID uuid.UUID) ([]UserAction, error)
  RecordUserAction(action *UserAction) error
}

type UserService interface {
  CreateUser(user *User) error
  GetUserProfile(userID uuid.UUID) (*User, error)
  UpdateUserProfile(user *User) error
  GetUserActionHistory(userID uuid.UUID) ([]UserAction, error)
}
  