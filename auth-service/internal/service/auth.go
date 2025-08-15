package service

import (
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"go.uber.org/zap"
	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"

	"github.com/ibm-techxchange/waste-management/auth-service/internal/model"
)

var (
	ErrUserExists         = errors.New("user already exists")
	ErrInvalidCredentials = errors.New("invalid credentials")
	ErrInvalidToken       = errors.New("invalid token")
	ErrUserNotFound       = errors.New("user not found")
)

type AuthServiceImpl struct {
	userRepo  model.UserRepository
	jwtSecret []byte
	logger    *zap.Logger
}

func NewAuthService(repo model.UserRepository, jwtSecret string, logger *zap.Logger) *AuthServiceImpl {
	return &AuthServiceImpl{
		userRepo:  repo,
		jwtSecret: []byte(jwtSecret),
		logger:    logger,
	}
}

func (s *AuthServiceImpl) Register(email, password string, role model.UserRole) (*model.User, error) {
	existingUser, err := s.userRepo.FindByEmail(email)
	if err != nil && !errors.Is(err, gorm.ErrRecordNotFound) {
		s.logger.Error("Failed to check existing user", zap.Error(err), zap.String("email", email))
		return nil, fmt.Errorf("user check failed: %w", err)
	}
	if existingUser != nil {
		return nil, ErrUserExists
	}

	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		s.logger.Error("Failed to hash password", zap.Error(err))
		return nil, fmt.Errorf("password hashing failed: %w", err)
	}

	user := &model.User{
		Email:        email,
		PasswordHash: string(hashedPassword),
		Role:         role,
	}

	if err := s.userRepo.Create(user); err != nil {
		s.logger.Error("Failed to create user", zap.Error(err), zap.String("email", email))
		return nil, fmt.Errorf("user creation failed: %w", err)
	}

	s.logger.Info("User registered successfully", zap.String("email", email), zap.String("role", string(role)))
	return user, nil
}

func (s *AuthServiceImpl) Login(email, password string) (string, error) {
	user, err := s.userRepo.FindByEmail(email)
	if err != nil {
		s.logger.Info("Login attempt with non-existent user", zap.String("email", email))
		return "", ErrInvalidCredentials
	}

	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(password)); err != nil {
		s.logger.Info("Invalid password attempt", zap.String("email", email))
		return "", ErrInvalidCredentials
	}

	if err := s.userRepo.UpdateLastLogin(user.ID); err != nil {
		s.logger.Error("Failed to update last login during login", zap.Error(err), zap.Uint("user_id", user.ID))
		return "", fmt.Errorf("last login update failed: %w", err)
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"user_id": user.ID,
		"email":   user.Email,
		"role":    user.Role,
		"exp":     time.Now().Add(24 * time.Hour).Unix(),
		"iat":     time.Now().Unix(),
	})

	tokenString, err := token.SignedString(s.jwtSecret)
	if err != nil {
		s.logger.Error("Failed to sign JWT token", zap.Error(err), zap.String("email", email))
		return "", fmt.Errorf("token signing failed: %w", err)
	}

	s.logger.Info("User logged in successfully", zap.String("email", email))
	return tokenString, nil
}

func (s *AuthServiceImpl) ValidateToken(tokenString string) (*model.User, error) {
	token, err := jwt.Parse(tokenString, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return s.jwtSecret, nil
	})

	if err != nil {
		s.logger.Error("JWT parsing failed", zap.Error(err))
		return nil, ErrInvalidToken
	}

	if !token.Valid {
		s.logger.Info("Invalid JWT token provided")
		return nil, ErrInvalidToken
	}

	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		s.logger.Error("Invalid JWT claims")
		return nil, ErrInvalidToken
	}

	email, ok := claims["email"].(string)
	if !ok || email == "" {
		s.logger.Error("Invalid token payload: missing email")
		return nil, ErrInvalidToken
	}

	user, err := s.userRepo.FindByEmail(email)
	if err != nil {
		s.logger.Error("User not found during token validation", zap.Error(err), zap.String("email", email))
		return nil, ErrUserNotFound
	}

	s.logger.Info("Token validated successfully", zap.String("email", email))
	return user, nil
}
