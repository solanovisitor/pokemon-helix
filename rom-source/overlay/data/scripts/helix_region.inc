@ Trusted actions for the fixture region. No generated code, new individuals,
@ birth rewards, clock gates, or writes to older quest/identity records.
HelixRegion_EventScript_Guide::
	lock
	faceplayer
	setvar VAR_0x8005, 0
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_Cancel
	closemessage
	warp MAP_HELIX_FIELD_VILLAGE, 15, 24
	waitstate
	release
	end

HelixRegion_EventScript_Return::
	lock
	faceplayer
	special ClearHelixQuestPreview
	setvar VAR_0x8007, 1
	special ShowHelixQuestMenu
	waitstate
	goto_if_eq VAR_RESULT, 0, HelixQuest_ReturnTravel
	goto_if_eq VAR_RESULT, 1, HelixQuest_GuideTask
	goto_if_eq VAR_RESULT, 2, HelixQuest_Notes
	goto HelixQuest_End
HelixQuest_ReturnTravel:
	special ClearHelixQuestPreview
	setvar VAR_0x8005, 1
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_Cancel
	closemessage
	warp MAP_OLDALE_TOWN, 12, 12
	waitstate
	release
	end

HelixRegion_EventScript_Researcher::
	lock
	faceplayer
	special ClearHelixQuestPreview
	setvar VAR_0x8007, 2
	special ShowHelixQuestMenu
	waitstate
	goto_if_eq VAR_RESULT, 0, HelixRegion_ResearchOriginal
	goto_if_eq VAR_RESULT, 1, HelixQuest_Reference
	goto_if_eq VAR_RESULT, 2, HelixQuest_Notes
	goto HelixQuest_End
HelixRegion_ResearchOriginal:
	special ClearHelixQuestPreview
	special CheckHelixRegionCompanion
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
	special GetHelixRegionState
	goto_if_eq VAR_RESULT, 15, HelixRegion_Guidebook
	goto_if_eq VAR_RESULT, 7, HelixRegion_Compare
	goto_if_ne VAR_RESULT, 0, HelixRegion_Instructions
	setvar VAR_0x8005, 2
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_Cancel
	setvar VAR_0x8006, 1
	special CommitHelixRegionAction
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
	setvar VAR_0x8005, 22
	call HelixRegion_Say
	goto HelixRegion_End

HelixRegion_Instructions:
	setvar VAR_0x8005, 3
	call HelixRegion_Say
	goto HelixRegion_End

HelixRegion_Compare:
	setvar VAR_0x8005, 10
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_Wrong
	setvar VAR_0x8005, 12
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_Cancel
	setvar VAR_0x8006, 4
	special CommitHelixRegionAction
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
HelixRegion_Guidebook:
	setvar VAR_0x8005, 13
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_Wrong:
	setvar VAR_0x8005, 11
	call HelixRegion_Say
	goto HelixRegion_End

HelixRegion_EventScript_Shelter::
	lock
	faceplayer
	setvar VAR_0x8006, 2
	goto HelixRegion_Observe
HelixRegion_EventScript_Exposure::
	lock
	faceplayer
	setvar VAR_0x8006, 3
HelixRegion_Observe:
	special CheckHelixRegionCompanion
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
	special GetHelixRegionState
	goto_if_eq VAR_RESULT, 0, HelixRegion_NotStarted
	goto_if_eq VAR_RESULT, 15, HelixRegion_AlreadyObserved
	goto_if_eq VAR_RESULT, 7, HelixRegion_AlreadyObserved
	goto_if_eq VAR_0x8006, 3, HelixRegion_ExposureCheck
	goto_if_eq VAR_RESULT, 3, HelixRegion_AlreadyObserved
	setvar VAR_0x8005, 4
	goto HelixRegion_ObserveAsk
HelixRegion_ExposureCheck:
	goto_if_eq VAR_RESULT, 5, HelixRegion_AlreadyObserved
	setvar VAR_0x8005, 5
HelixRegion_ObserveAsk:
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_Cancel
	setvar VAR_0x8005, 6
	special BufferHelixRegionText
	showmonpic VAR_0x8009, 2, 1
	msgbox gStringVar4, MSGBOX_DEFAULT
	hidemonpic
	setvar VAR_0x8005, 7
	goto_if_eq VAR_0x8006, 2, HelixRegion_RecordAsk
	setvar VAR_0x8005, 8
HelixRegion_RecordAsk:
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_Cancel
	special CommitHelixRegionAction
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
	setvar VAR_0x8005, 9
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_AlreadyObserved:
	setvar VAR_0x8005, 21
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_NotStarted:
	setvar VAR_0x8005, 20
	call HelixRegion_Say
	goto HelixRegion_End

HelixRegion_EventScript_Villager::
	lock
	faceplayer
	special CheckHelixRegionCompanion
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
	special GetHelixRegionState
	goto_if_ne VAR_RESULT, 15, HelixRegion_UtilityNeedGuide
	special GetHelixUtilityState
	goto_if_eq VAR_RESULT, 1, HelixRegion_UtilityInstructions
	goto_if_ne VAR_RESULT, 0, HelixRegion_CareResident
	setvar VAR_0x8005, 23
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_UtilityCancel
	setvar VAR_0x8006, 5
	special CommitHelixRegionAction
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
HelixRegion_UtilityInstructions:
	setvar VAR_0x8005, 25
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_UtilityThanks:
	setvar VAR_0x8005, 35
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_CareResident:
	special GetHelixCareState
	goto_if_eq VAR_RESULT, 1, HelixRegion_CareInstructions
	goto_if_eq VAR_RESULT, 2, HelixRegion_CareThanks
	setvar VAR_0x8005, 37
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_CareCancel
	setvar VAR_0x8006, 8
	special CommitHelixRegionAction
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
HelixRegion_CareInstructions:
	setvar VAR_0x8005, 38
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_CareThanks:
	setvar VAR_0x8005, 44
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_UtilityNeedGuide:
	setvar VAR_0x8005, 24
	call HelixRegion_Say
	goto HelixRegion_End

HelixRegion_EventScript_UtilityWall::
	lockall
	setvar VAR_0x8006, 6
	goto HelixRegion_UtilitySite
HelixRegion_EventScript_UtilityReeds::
	lockall
	setvar VAR_0x8006, 7
HelixRegion_UtilitySite:
	special CheckHelixRegionCompanion
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
	special GetHelixRegionState
	goto_if_ne VAR_RESULT, 15, HelixRegion_UtilityNeedGuide
	special GetHelixUtilityState
	goto_if_eq VAR_RESULT, 0, HelixRegion_UtilityMeetVillager
	goto_if_eq VAR_0x8006, 7, HelixRegion_UtilityReedsCheck
	goto_if_eq VAR_RESULT, 2, HelixRegion_CareSite
	setvar VAR_0x8005, 26
	goto HelixRegion_UtilityTry
HelixRegion_UtilityReedsCheck:
	goto_if_eq VAR_RESULT, 3, HelixRegion_CareSite
	setvar VAR_0x8005, 27
HelixRegion_UtilityTry:
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_UtilityCancel
	setvar VAR_0x8005, 28
	special BufferHelixRegionText
	showmonpic VAR_0x8009, 2, 1
	msgbox gStringVar4, MSGBOX_DEFAULT
	hidemonpic
	special GetHelixUtilityState
	setvar VAR_0x8005, 29
	goto_if_eq VAR_RESULT, 1, HelixRegion_UtilityConfirm
	setvar VAR_0x8005, 30
HelixRegion_UtilityConfirm:
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_UtilityCancel
	special CommitHelixRegionAction
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
	call HelixRegion_ApplyUtilityLayout
	special DrawWholeMapView
	setvar VAR_0x8005, 31
	goto_if_eq VAR_0x8006, 6, HelixRegion_UtilityDone
	setvar VAR_0x8005, 32
HelixRegion_UtilityDone:
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_UtilityAlready:
	setvar VAR_0x8005, 34
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_CareSite:
	special GetHelixCareState
	goto_if_eq VAR_RESULT, 0, HelixRegion_CareMeetVillager
	goto_if_eq VAR_RESULT, 2, HelixRegion_CareReplay
	setvar VAR_0x8005, 45
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_CareCancel
	setvar VAR_0x8005, 39
	special BufferHelixRegionText
	showmonpic VAR_0x8009, 2, 1
	msgbox gStringVar4, MSGBOX_DEFAULT
	hidemonpic
	setvar VAR_0x8005, 40
	call HelixRegion_Ask
	goto_if_ne VAR_RESULT, YES, HelixRegion_CareCancel
	setvar VAR_0x8006, 9
	special CommitHelixRegionAction
	goto_if_ne VAR_RESULT, 1, HelixRegion_Unavailable
	setvar VAR_0x8005, 41
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_CareMeetVillager:
	setvar VAR_0x8005, 46
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_CareReplay:
	setvar VAR_0x8005, 43
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_CareCancel:
	setvar VAR_0x8005, 42
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_UtilityMeetVillager:
	setvar VAR_0x8005, 36
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_UtilityCancel:
	setvar VAR_0x8005, 33
	call HelixRegion_Say
	goto HelixRegion_End

@ Only the existing village invokes this trusted load/update script.
@ Both cells remain solid: relocating the single bench cannot trap a save.
HelixRegion_ApplyUtilityLayout::
	special GetHelixUtilityState
	setmetatile 8, 8, 3, TRUE
	setmetatile 6, 21, 3, TRUE
	goto_if_eq VAR_RESULT, 2, HelixRegion_LayoutWall
	goto_if_eq VAR_RESULT, 3, HelixRegion_LayoutReeds
	return
HelixRegion_LayoutWall:
	setmetatile 8, 8, 5, TRUE
	return
HelixRegion_LayoutReeds:
	setmetatile 6, 21, 5, TRUE
	return

HelixRegion_EventScript_Sign::
	lockall
	special GetHelixQuestLocation
	goto_if_ne VAR_RESULT, 3, HelixRegion_SignDirections
	special ClearHelixQuestPreview
	setvar VAR_0x8007, 3
	special ShowHelixQuestMenu
	waitstate
	goto_if_eq VAR_RESULT, 0, HelixRegion_SignDirections
	goto_if_eq VAR_RESULT, 1, HelixQuest_Scratches
	goto_if_eq VAR_RESULT, 2, HelixQuest_Test
	goto_if_eq VAR_RESULT, 3, HelixQuest_Solution
	goto_if_eq VAR_RESULT, 4, HelixQuest_Notes
	goto HelixQuest_End
HelixRegion_SignDirections:
	special ClearHelixQuestPreview
	setvar VAR_0x8005, 17
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_EventScript_Care::
	lock
	faceplayer
	setvar VAR_0x8004, 4
	special BufferHelixLabPage
	msgbox gStringVar4, MSGBOX_YESNO
	goto_if_ne VAR_RESULT, YES, HelixRegion_End
	special HealPlayerParty
	setvar VAR_0x8004, 5
	special BufferHelixLabPage
	msgbox gStringVar4, MSGBOX_DEFAULT
	goto HelixRegion_End

HelixRegion_Cancel:
	setvar VAR_0x8005, 14
	call HelixRegion_Say
	goto HelixRegion_End
HelixRegion_Unavailable:
	setvar VAR_0x8005, 15
	call HelixRegion_Say
HelixRegion_End:
	closemessage
	releaseall
	end
HelixRegion_Say:
	special BufferHelixRegionText
	msgbox gStringVar4, MSGBOX_DEFAULT
	return
HelixRegion_Ask:
	special BufferHelixRegionText
	msgbox gStringVar4, MSGBOX_YESNO
	return
