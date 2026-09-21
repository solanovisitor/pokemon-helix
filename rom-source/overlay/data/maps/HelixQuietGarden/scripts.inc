HelixQuietGarden_MapScripts::
	map_script MAP_SCRIPT_ON_LOAD, HelixQuietGarden_OnLoad
	.byte 0
HelixQuietGarden_OnLoad:
	call HelixExpansion_ApplyLayout
	end
