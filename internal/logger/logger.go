package logger

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"

	"github.com/PhiFever/nightreign-overlay-helper/pkg/utils"
)

// Level represents log level
type Level int

const (
	DEBUG Level = iota
	INFO
	WARNING
	ERROR
	CRITICAL
)

var levelNames = map[Level]string{
	DEBUG:    "DEBUG",
	INFO:     "INFO",
	WARNING:  "WARNING",
	ERROR:    "ERROR",
	CRITICAL: "CRITICAL",
}

// Logger is the main logger structure
type Logger struct {
	level   Level
	writers []io.Writer
	mu      sync.Mutex
}

var (
	globalLogger *Logger
	loggerMu     sync.Mutex
)

// Setup initializes the global logger with the specified level
func Setup(level Level) (*Logger, error) {
	loggerMu.Lock()
	defer loggerMu.Unlock()

	if globalLogger != nil {
		return globalLogger, nil
	}

	logger := &Logger{
		level:   level,
		writers: []io.Writer{os.Stdout},
	}

	// Create log directory
	logDir, err := utils.GetAppDataPath("logs")
	if err != nil {
		return nil, err
	}

	if err := os.MkdirAll(filepath.Dir(logDir), 0755); err != nil {
		return nil, err
	}

	// Create log file
	date := time.Now().Format("2006-01-02")
	logFile := filepath.Join(filepath.Dir(logDir), "logs", date+".log")

	if err := os.MkdirAll(filepath.Dir(logFile), 0755); err != nil {
		return nil, err
	}

	file, err := os.OpenFile(logFile, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return nil, err
	}

	logger.writers = append(logger.writers, file)
	globalLogger = logger

	return logger, nil
}

// SetLevel sets the logging level
func SetLevel(level Level) {
	loggerMu.Lock()
	defer loggerMu.Unlock()

	if globalLogger == nil {
		globalLogger, _ = Setup(level)
	} else {
		globalLogger.level = level
	}
}

// GetLogger returns the global logger
func GetLogger() *Logger {
	loggerMu.Lock()
	defer loggerMu.Unlock()

	if globalLogger == nil {
		globalLogger, _ = Setup(INFO)
	}

	return globalLogger
}

// log writes a log message with the specified level
func (l *Logger) log(level Level, msg string, includeTrace bool) {
	if level < l.level {
		return
	}

	l.mu.Lock()
	defer l.mu.Unlock()

	timestamp := time.Now().Format("2006-01-02 15:04:05")
	levelName := levelNames[level]

	logMsg := fmt.Sprintf("%s [%s] %s\n", timestamp, levelName, msg)

	for _, w := range l.writers {
		w.Write([]byte(logMsg))
	}

	if includeTrace && level >= ERROR {
		trace := getStackTrace()
		traceMsg := fmt.Sprintf("%s [%s] %s\n", timestamp, levelName, trace)
		for _, w := range l.writers {
			w.Write([]byte(traceMsg))
		}
	}
}

// Debug logs a debug message
func Debug(msg string) {
	GetLogger().log(DEBUG, msg, false)
}

// Debugf logs a formatted debug message
func Debugf(format string, args ...interface{}) {
	GetLogger().log(DEBUG, fmt.Sprintf(format, args...), false)
}

// Info logs an info message
func Info(msg string) {
	GetLogger().log(INFO, msg, false)
}

// Infof logs a formatted info message
func Infof(format string, args ...interface{}) {
	GetLogger().log(INFO, fmt.Sprintf(format, args...), false)
}

// Warning logs a warning message
func Warning(msg string) {
	GetLogger().log(WARNING, msg, false)
}

// Warningf logs a formatted warning message
func Warningf(format string, args ...interface{}) {
	GetLogger().log(WARNING, fmt.Sprintf(format, args...), false)
}

// Error logs an error message with stack trace
func Error(msg string) {
	GetLogger().log(ERROR, msg, true)
}

// Errorf logs a formatted error message with stack trace
func Errorf(format string, args ...interface{}) {
	GetLogger().log(ERROR, fmt.Sprintf(format, args...), true)
}

// ErrorNoTrace logs an error message without stack trace
func ErrorNoTrace(msg string) {
	GetLogger().log(ERROR, msg, false)
}

// Critical logs a critical message with stack trace
func Critical(msg string) {
	GetLogger().log(CRITICAL, msg, true)
}

// Criticalf logs a formatted critical message with stack trace
func Criticalf(format string, args ...interface{}) {
	GetLogger().log(CRITICAL, fmt.Sprintf(format, args...), true)
}

// getStackTrace returns the current stack trace
func getStackTrace() string {
	buf := make([]byte, 4096)
	n := runtime.Stack(buf, false)
	return string(buf[:n])
}
