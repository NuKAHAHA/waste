package model

import (
	"time"

	"gorm.io/gorm"
)

type UserRole string

const (
	RoleUser      UserRole = "user"
	RoleAdmin     UserRole = "admin"
	RoleCollector UserRole = "collector"
)

type User struct {
	gorm.Model
	Email        string   `gorm:"unique;not null"`
	PasswordHash string   `gorm:"not null"`
	Role         UserRole `gorm:"not null;default:'user'"`
	LastLogin    time.Time
	ProfileImage string
}

type UserRepository interface {
	Create(user *User) error
	FindByEmail(email string) (*User, error)
	UpdateLastLogin(userID uint) error
}

type AuthService interface {
	Register(email, password string, role UserRole) (*User, error)
	Login(email, password string) (string, error)
	ValidateToken(tokenString string) (*User, error)
}
