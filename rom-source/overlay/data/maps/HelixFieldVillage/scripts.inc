HelixFieldVillage_MapScripts::
	map_script MAP_SCRIPT_ON_LOAD, HelixFieldVillage_OnLoad
	.byte 0

HelixFieldVillage_OnLoad:
	call HelixRegion_ApplyUtilityLayout
	end
