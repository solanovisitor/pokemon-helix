@ The sign and the wind: authored finite quest, native UI, no runtime inference.
@ Callers already lock the scene. Every terminal branch clears the hold/releases.
@ Page/action/menu IDs are documented in include/helix_quest.h.

HelixQuest_GuideTask:
	special GetHelixQuestState
	goto_if_eq VAR_RESULT, 65535, HelixQuest_Invalid
	goto_if_eq VAR_RESULT, 3, HelixQuest_Result
	goto_if_eq VAR_RESULT, 2, HelixQuest_Notes
	goto_if_eq VAR_RESULT, 1, HelixQuest_GuideReport
	setvar VAR_0x8005, 0
	special BufferHelixQuestText
	msgbox gStringVar4, MSGBOX_YESNO
	goto_if_ne VAR_RESULT, YES, HelixQuest_Declined
	setvar VAR_0x8006, 1
	special CommitHelixQuestAction
	goto_if_eq VAR_RESULT, 0, HelixQuest_Invalid
	setvar VAR_0x8005, 2
	call HelixQuest_Say
	goto HelixQuest_End

HelixQuest_GuideReport:
	setvar VAR_0x8006, 4
	special CommitHelixQuestAction
	goto_if_eq VAR_RESULT, 0, HelixQuest_Invalid
	setvar VAR_0x8005, 4
	call HelixQuest_Say
	closemessage
	setvar VAR_0x8007, 5
	special ShowHelixQuestMenu
	waitstate
	goto_if_eq VAR_RESULT, 0, HelixQuest_Joint
	goto_if_eq VAR_RESULT, 1, HelixQuest_Moved
	goto HelixQuest_End
HelixQuest_Joint:
	setvar VAR_0x8006, 5
	special CommitHelixQuestAction
	goto_if_eq VAR_RESULT, 0, HelixQuest_Invalid
	setvar VAR_0x8005, 6
	call HelixQuest_Say
	goto HelixQuest_End
HelixQuest_Moved:
	setvar VAR_0x8006, 6
	special CommitHelixQuestAction
	goto_if_eq VAR_RESULT, 0, HelixQuest_Invalid
	setvar VAR_0x8005, 7
	call HelixQuest_Say
	goto HelixQuest_End

HelixQuest_Reference:
	setvar VAR_0x8006, 3
	special CommitHelixQuestAction
	goto_if_eq VAR_RESULT, 0, HelixQuest_Invalid
	setvar VAR_0x8005, 5
	call HelixQuest_Say
	goto HelixQuest_End
HelixQuest_Scratches:
	setvar VAR_0x8006, 2
	special CommitHelixQuestAction
	goto_if_eq VAR_RESULT, 0, HelixQuest_Invalid
	setvar VAR_0x8005, 3
	call HelixQuest_Say
	goto HelixQuest_End

HelixQuest_Test:
	special GetHelixQuestState
	goto_if_eq VAR_RESULT, 65535, HelixQuest_Invalid
	goto_if_eq VAR_RESULT, 0, HelixQuest_NotStarted
	goto_if_eq VAR_RESULT, 3, HelixQuest_Result
	goto_if_eq VAR_RESULT, 2, HelixQuest_Notes
	goto_if_ne VAR_0x800A, 1, HelixQuest_Unavailable
	goto_if_eq VAR_0x8008, 3, HelixQuest_Prepare
	goto_if_eq VAR_0x8008, 7, HelixQuest_Prepare
	setvar VAR_0x8005, 13
	call HelixQuest_Say
	goto HelixQuest_End
HelixQuest_Prepare:
	setvar VAR_0x8006, 7
	special CommitHelixQuestAction
	goto_if_ne VAR_RESULT, 1, HelixQuest_Unavailable
	setvar VAR_0x8005, 27
	special BufferHelixQuestText
	showmonpic VAR_0x8009, 2, 1
	msgbox gStringVar4, MSGBOX_DEFAULT
	hidemonpic
	closemessage
	setvar VAR_0x8007, 4
	special ShowHelixQuestMenu
	waitstate
	goto_if_ne VAR_RESULT, 0, HelixQuest_Cancelled
	setvar VAR_0x8006, 8
	special CommitHelixQuestAction
	goto_if_ne VAR_RESULT, 1, HelixQuest_Unavailable
	setvar VAR_0x8005, 28
	call HelixQuest_Say
	goto HelixQuest_End

HelixQuest_Solution:
	special GetHelixQuestState
	goto_if_eq VAR_RESULT, 65535, HelixQuest_Invalid
	goto_if_eq VAR_RESULT, 0, HelixQuest_NotStarted
	goto_if_eq VAR_RESULT, 3, HelixQuest_Result
	goto_if_eq VAR_RESULT, 1, HelixQuest_NeedTest
	goto_if_ne VAR_0x800A, 1, HelixQuest_Unavailable
@ Both costs are shown before the direct choice. No second confirmation.
	setvar VAR_0x8005, 16
	call HelixQuest_Say
	setvar VAR_0x8005, 17
	call HelixQuest_Say
	setvar VAR_0x8005, 18
	call HelixQuest_Say
	closemessage
	setvar VAR_0x8007, 6
	special ShowHelixQuestMenu
	waitstate
	goto_if_eq VAR_RESULT, 0, HelixQuest_Lock
	goto_if_eq VAR_RESULT, 1, HelixQuest_Split
	goto HelixQuest_Cancelled
HelixQuest_Lock:
	setvar VAR_0x8006, 9
	goto HelixQuest_Install
HelixQuest_Split:
	setvar VAR_0x8006, 10
HelixQuest_Install:
	special CommitHelixQuestAction
	goto_if_eq VAR_RESULT, 0, HelixQuest_Unavailable
HelixQuest_Result:
	setvar VAR_0x8005, 29
	call HelixQuest_Say
	goto HelixQuest_End

HelixQuest_Notes:
	setvar VAR_0x8005, 24
	call HelixQuest_Say
	goto HelixQuest_End
HelixQuest_NotStarted:
	setvar VAR_0x8005, 25
	call HelixQuest_Say
	goto HelixQuest_End
HelixQuest_NeedTest:
	setvar VAR_0x8005, 26
	call HelixQuest_Say
	goto HelixQuest_End
HelixQuest_Declined:
	setvar VAR_0x8005, 1
	call HelixQuest_Say
	goto HelixQuest_End
HelixQuest_Cancelled:
	special ClearHelixQuestPreview
	setvar VAR_0x8005, 14
	call HelixQuest_Say
	goto HelixQuest_End
HelixQuest_Unavailable:
	setvar VAR_0x8005, 12
	call HelixQuest_Say
	goto HelixQuest_End
HelixQuest_Invalid:
	setvar VAR_0x8005, 23
	call HelixQuest_Say
HelixQuest_End:
	special ClearHelixQuestPreview
	closemessage
	releaseall
	end
HelixQuest_Say:
	special BufferHelixQuestText
	msgbox gStringVar4, MSGBOX_DEFAULT
	return
