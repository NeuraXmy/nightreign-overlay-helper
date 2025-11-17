package utils

import (
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// LoadYAML loads a YAML file into a map
func LoadYAML(path string) (map[string]interface{}, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var result map[string]interface{}
	if err := yaml.Unmarshal(data, &result); err != nil {
		return nil, err
	}

	return result, nil
}

// SaveYAML saves a map to a YAML file
// Uses atomic write (write to temp file then replace) to prevent corruption
func SaveYAML(path string, data interface{}) error {
	// Ensure directory exists
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}

	// Write to temporary file
	tmpPath := path + ".tmp"
	yamlData, err := yaml.Marshal(data)
	if err != nil {
		return err
	}

	if err := os.WriteFile(tmpPath, yamlData, 0644); err != nil {
		return err
	}

	// Atomic replace
	if err := os.Rename(tmpPath, path); err != nil {
		os.Remove(tmpPath) // Clean up on error
		return err
	}

	return nil
}
