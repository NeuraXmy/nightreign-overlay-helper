package main

import (
	"fmt"
	"os"

	"github.com/PhiFever/nightreign-overlay-helper/internal/config"
	"github.com/PhiFever/nightreign-overlay-helper/internal/logger"
	"github.com/PhiFever/nightreign-overlay-helper/pkg/version"
)

func main() {
	fmt.Printf("Starting %s...\n", version.GetFullName())

	// Initialize logger
	if _, err := logger.Setup(logger.INFO); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to setup logger: %v\n", err)
		os.Exit(1)
	}

	logger.Info("Logger initialized")
	logger.Infof("Application: %s", version.GetFullName())
	logger.Infof("Version: %s", version.Version)
	logger.Infof("Author: %s", version.Author)

	// Load configuration
	cfg, err := config.Get()
	if err != nil {
		logger.Errorf("Failed to load configuration: %v", err)
		os.Exit(1)
	}

	logger.Info("Configuration loaded successfully")
	logger.Debugf("Update interval: %.2f seconds", cfg.UpdateInterval)
	logger.Debugf("Time scale: %.2f", cfg.TimeScale)

	// TODO: Initialize detectors
	logger.Info("TODO: Initialize detectors")

	// TODO: Initialize UI
	logger.Info("TODO: Initialize UI")

	// TODO: Start main loop
	logger.Info("TODO: Start main loop")

	logger.Info("Application started successfully")
	logger.Info("Press Ctrl+C to exit")

	// Keep the application running
	select {}
}
