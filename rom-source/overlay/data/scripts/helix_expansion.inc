@ Authored v1 garden quest. Scene-local preparation never survives leaving.
HelixExpansion_EventScript_Travel::
	lock
	faceplayer
	setvar VAR_0x8005, 0
	special BufferHelixExpansionText
	msgbox gStringVar4, MSGBOX_YESNO
	goto_if_ne VAR_RESULT, YES, HelixExpansion_End
	closemessage
	warp MAP_HELIX_QUIET_GARDEN, 10, 17
	waitstate
	goto HelixExpansion_End
HelixExpansion_EventScript_Return::
	lock
	faceplayer
	setvar VAR_0x8005, 1
	special BufferHelixExpansionText
	msgbox gStringVar4, MSGBOX_YESNO
	goto_if_ne VAR_RESULT, YES, HelixExpansion_End
	closemessage
	warp MAP_HELIX_SHELTER_TRAIL, 18, 16
	waitstate
	goto HelixExpansion_End
HelixExpansion_EventScript_Lia::
	lock
	faceplayer
	special GetHelixExpansionState
	goto_if_eq VAR_RESULT, 65535, HelixExpansion_Invalid
	goto_if_eq VAR_RESULT, 3, HelixExpansion_Result
	goto_if_ne VAR_RESULT, 0, HelixExpansion_Notes
	setvar VAR_0x8005, 2
	special BufferHelixExpansionText
	msgbox gStringVar4, MSGBOX_YESNO
	goto_if_ne VAR_RESULT, YES, HelixExpansion_Declined
	setvar VAR_0x8006, 1
	special CommitHelixExpansionAction
	goto_if_eq VAR_RESULT, 0, HelixExpansion_Invalid
	setvar VAR_0x8005, 4
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_EventScript_Tom::
	lock
	faceplayer
	special GetHelixExpansionState
	goto_if_eq VAR_RESULT, 65535, HelixExpansion_Invalid
	goto_if_eq VAR_RESULT, 3, HelixExpansion_Result
	setvar VAR_0x8005, 7
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_EventScript_Bed::
	lockall
	setvar VAR_0x8006, 2
	special CommitHelixExpansionAction
	goto_if_eq VAR_RESULT, 0, HelixExpansion_Invalid
	setvar VAR_0x8005, 5
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_EventScript_Mouth::
	lockall
	setvar VAR_0x8006, 3
	special CommitHelixExpansionAction
	goto_if_eq VAR_RESULT, 0, HelixExpansion_Invalid
	setvar VAR_0x8005, 6
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_EventScript_Board::
	lockall
	special ClearHelixExpansionPreview
	setvar VAR_0x8007, 1
	special ShowHelixExpansionMenu
	waitstate
	goto_if_eq VAR_RESULT, 0, HelixExpansion_Test
	goto_if_eq VAR_RESULT, 1, HelixExpansion_Choice
	goto_if_eq VAR_RESULT, 2, HelixExpansion_Notes
	goto HelixExpansion_End
HelixExpansion_Test:
	special GetHelixExpansionState
	goto_if_eq VAR_RESULT, 65535, HelixExpansion_Invalid
	goto_if_eq VAR_RESULT, 0, HelixExpansion_NotStarted
	goto_if_eq VAR_RESULT, 3, HelixExpansion_Result
	goto_if_eq VAR_RESULT, 2, HelixExpansion_Notes
	goto_if_ne VAR_0x800A, 1, HelixExpansion_Unavailable
	goto_if_ne VAR_0x8008, 3, HelixExpansion_NeedClues
	setvar VAR_0x8006, 4
	special CommitHelixExpansionAction
	goto_if_ne VAR_RESULT, 1, HelixExpansion_Unavailable
	setvar VAR_0x8005, 23
	special BufferHelixExpansionText
	showmonpic VAR_0x8009, 2, 1
	msgbox gStringVar4, MSGBOX_DEFAULT
	hidemonpic
	closemessage
	setvar VAR_0x8007, 2
	special ShowHelixExpansionMenu
	waitstate
	goto_if_ne VAR_RESULT, 0, HelixExpansion_Cancelled
	setvar VAR_0x8006, 5
	special CommitHelixExpansionAction
	goto_if_ne VAR_RESULT, 1, HelixExpansion_Unavailable
	setvar VAR_0x8005, 10
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_Choice:
	special GetHelixExpansionState
	goto_if_eq VAR_RESULT, 65535, HelixExpansion_Invalid
	goto_if_eq VAR_RESULT, 0, HelixExpansion_NotStarted
	goto_if_eq VAR_RESULT, 3, HelixExpansion_Result
	goto_if_eq VAR_RESULT, 1, HelixExpansion_NeedTest
	goto_if_ne VAR_0x800A, 1, HelixExpansion_Unavailable
	setvar VAR_0x8005, 11
	call HelixExpansion_Say
	setvar VAR_0x8005, 12
	call HelixExpansion_Say
	closemessage
	setvar VAR_0x8007, 3
	special ShowHelixExpansionMenu
	waitstate
	goto_if_eq VAR_RESULT, 0, HelixExpansion_ChooseBed
	goto_if_eq VAR_RESULT, 1, HelixExpansion_ChooseMouth
	goto HelixExpansion_Cancelled
HelixExpansion_ChooseBed:
	setvar VAR_0x8006, 6
	goto HelixExpansion_Install
HelixExpansion_ChooseMouth:
	setvar VAR_0x8006, 7
HelixExpansion_Install:
	special CommitHelixExpansionAction
	goto_if_eq VAR_RESULT, 0, HelixExpansion_Unavailable
	call HelixExpansion_ApplyLayout
	special DrawWholeMapView
HelixExpansion_Result:
	setvar VAR_0x8005, 24
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_Notes:
	setvar VAR_0x8005, 22
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_Invalid:
	setvar VAR_0x8005, 19
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_NotStarted:
	setvar VAR_0x8005, 20
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_NeedClues:
	setvar VAR_0x8005, 17
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_NeedTest:
	setvar VAR_0x8005, 18
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_Unavailable:
	setvar VAR_0x8005, 16
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_Declined:
	setvar VAR_0x8005, 3
	call HelixExpansion_Say
	goto HelixExpansion_End
HelixExpansion_Cancelled:
	special ClearHelixExpansionPreview
	setvar VAR_0x8005, 15
	call HelixExpansion_Say
HelixExpansion_End:
	special ClearHelixExpansionPreview
	closemessage
	releaseall
	end
HelixExpansion_Say:
	special BufferHelixExpansionText
	msgbox gStringVar4, MSGBOX_DEFAULT
	return

@ A stock solid marker shows the chosen screen support. Return remains open.
HelixExpansion_ApplyLayout::
	special GetHelixExpansionLayout
	setmetatile 6, 10, 1, FALSE
	setmetatile 14, 6, 1, FALSE
	goto_if_eq VAR_RESULT, 1, HelixExpansion_LayoutBed
	goto_if_eq VAR_RESULT, 2, HelixExpansion_LayoutMouth
	return
HelixExpansion_LayoutBed:
	setmetatile 6, 10, 3, TRUE
	return
HelixExpansion_LayoutMouth:
	setmetatile 14, 6, 3, TRUE
	return
