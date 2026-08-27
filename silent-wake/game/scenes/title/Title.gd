extends Control

const NEXT_SCENE := "res://scenes/placeholder/ComingSoon.tscn"
const SAVE_PATH := "user://silent_wake_save.json"

@onready var continue_button: Button = $CenterContainer/VBoxContainer/ButtonContainer/ContinueButton


func _ready() -> void:
	continue_button.disabled = not FileAccess.file_exists(SAVE_PATH)


func _on_new_game_button_pressed() -> void:
	get_tree().change_scene_to_file(NEXT_SCENE)


func _on_continue_button_pressed() -> void:
	get_tree().change_scene_to_file(NEXT_SCENE)


func _on_options_button_pressed() -> void:
	pass


func _on_quit_button_pressed() -> void:
	get_tree().quit()
