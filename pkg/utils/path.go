package utils

import (
	"os"
	"path/filepath"

	"github.com/PhiFever/nightreign-overlay-helper/pkg/version"
)

// GetAssetPath returns the path to an asset file
func GetAssetPath(path string) string {
	return filepath.Join("assets", path)
}

// GetDataPath returns the path to a data file
func GetDataPath(path string) string {
	return filepath.Join("data", path)
}

// GetAppDataPath returns the path to an application data file
func GetAppDataPath(filename string) (string, error) {
	var appDataDir string

	if appData := os.Getenv("APPDATA"); appData != "" {
		// Windows
		appDataDir = filepath.Join(appData, version.AppName)
	} else if home := os.Getenv("HOME"); home != "" {
		// Linux/macOS
		appDataDir = filepath.Join(home, ".local", "share", version.AppName)
	} else {
		// Fallback
		appDataDir = version.AppName
	}

	if err := os.MkdirAll(appDataDir, 0755); err != nil {
		return "", err
	}

	return filepath.Join(appDataDir, filename), nil
}

// GetDesktopPath returns the path to a desktop file
func GetDesktopPath(filename string) (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}

	desktop := filepath.Join(home, "Desktop")
	if err := os.MkdirAll(desktop, 0755); err != nil {
		return "", err
	}

	if filename != "" {
		return filepath.Join(desktop, filename), nil
	}
	return desktop, nil
}

// GetIconPath returns the path to the icon file
func GetIconPath() string {
	return GetAssetPath("icon.ico")
}
