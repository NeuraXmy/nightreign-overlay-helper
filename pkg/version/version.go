package version

const (
	// AppName is the name of the application
	AppName = "nightreign-overlay-helper"
	// AppNameCHS is the Chinese name of the application
	AppNameCHS = "黑夜君临悬浮助手"
	// Version is the current version
	Version = "0.9.0"
	// Author is the author of the application
	Author = "NeuraXmy"
	// GameWindowTitle is the title of the game window
	GameWindowTitle = "ELDEN RING NIGHTREIGN"
)

// GetFullName returns the full name with version
func GetFullName() string {
	return AppNameCHS + "v" + Version
}
