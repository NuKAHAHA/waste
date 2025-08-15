package database

import (
	"fmt"
	"os"

	"github.com/ibm-techxchange/waste-management/user-service/internal/domain"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func NewPostgresDatabase() (*gorm.DB, error) {
	dsn := fmt.Sprintf("host=%s user=%s password=%s dbname=%s port=%s sslmode=disable",
		os.Getenv("DB_HOST"),
		os.Getenv("DB_USER"),
		os.Getenv("DB_PASSWORD"),
		"user_service_db",
		os.Getenv("DB_PORT"),
	)

	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
	if err != nil {
		return nil, err
	}

	// Auto migrate model models
	err = db.AutoMigrate(&domain.User{}, &domain.UserAction{})
	if err != nil {
		return nil, err
	}

	return db, nil
}
