package repo

import (
	"fmt"
	"os"
	"time"

	"github.com/joho/godotenv"
	"go.uber.org/zap"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"

	"auth-service/internal/model"
)

type PostgresDatabase struct {
	DB     *gorm.DB
	logger *zap.Logger
}

func NewPostgresDatabase(logger *zap.Logger) (*PostgresDatabase, error) {
	// Загружаем .env файл
	if err := godotenv.Load(); err != nil {
		logger.Warn(".env file not found, using environment variables")
	}

	// Берём переменные окружения
	host := os.Getenv("DB_HOST")
	user := os.Getenv("DB_USER")
	password := os.Getenv("DB_PASSWORD")
	dbname := os.Getenv("DB_NAME")
	port := os.Getenv("DB_PORT")
	sslmode := os.Getenv("DB_SSLMODE")

	// Проверка на пустые переменные
	if host == "" || user == "" || password == "" || dbname == "" || port == "" {
		return nil, fmt.Errorf("database environment variables are not set properly")
	}

	// Если SSLMODE пустой — задаём по умолчанию
	if sslmode == "" {
		sslmode = "disable"
	}

	dsn := fmt.Sprintf(
		"host=%s user=%s password=%s dbname=%s port=%s sslmode=%s",
		host, user, password, dbname, port, sslmode,
	)

	// Подключение к базе
	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
	if err != nil {
		logger.Error("Failed to connect to database", zap.Error(err))
		return nil, fmt.Errorf("database connection failed: %w", err)
	}

	// Авто-миграция моделей
	if err = db.AutoMigrate(&model.User{}); err != nil {
		logger.Error("Failed to auto-migrate database", zap.Error(err))
		return nil, fmt.Errorf("auto-migration failed: %w", err)
	}

	logger.Info("Successfully connected to PostgreSQL", zap.String("host", host), zap.String("db", dbname))
	return &PostgresDatabase{DB: db, logger: logger}, nil
}

func (pd *PostgresDatabase) Create(user *model.User) error {
	if err := pd.DB.Create(user).Error; err != nil {
		pd.logger.Error("Failed to create user", zap.Error(err), zap.String("email", user.Email))
		return fmt.Errorf("user creation failed: %w", err)
	}
	return nil
}

func (pd *PostgresDatabase) FindByEmail(email string) (*model.User, error) {
	var user model.User
	result := pd.DB.Where("email = ?", email).First(&user)
	if result.Error != nil {
		if result.Error == gorm.ErrRecordNotFound {
			pd.logger.Info("User not found", zap.String("email", email))
			return nil, result.Error
		}
		pd.logger.Error("Failed to find user by email", zap.Error(result.Error), zap.String("email", email))
		return nil, fmt.Errorf("user lookup failed: %w", result.Error)
	}
	return &user, nil
}

func (pd *PostgresDatabase) UpdateLastLogin(userID uint) error {
	if err := pd.DB.Model(&model.User{}).Where("id = ?", userID).Update("last_login", time.Now()).Error; err != nil {
		pd.logger.Error("Failed to update last login", zap.Error(err), zap.Uint("user_id", userID))
		return fmt.Errorf("last login update failed: %w", err)
	}
	return nil
}
