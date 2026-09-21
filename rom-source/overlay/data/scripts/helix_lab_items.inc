@ Two lab items, one atomic simulated assay. Bridge only after explicit YES.
HelixLabItems_EventScript_Mira::
	lock
	faceplayer
	special ClearHelixLabItemsPreview
	special GetHelixLabItemsState
	goto_if_eq VAR_RESULT, 65535, HelixLabItems_Invalid
	goto_if_eq VAR_RESULT, 3, HelixLabItems_Result
	goto_if_eq VAR_RESULT, 1, HelixLabItems_NeedResident
	goto_if_eq VAR_RESULT, 2, HelixLabItems_Assay
	special GetHelixRegionState
	goto_if_ne VAR_RESULT, 15, HelixLabItems_NeedGuide
	setvar VAR_0x8005, 0
	special BufferHelixLabItemsText
	msgbox gStringVar4, MSGBOX_YESNO
	goto_if_ne VAR_RESULT, YES, HelixLabItems_Cancelled
	setvar VAR_0x8006, 1
	special CommitHelixLabItemsAction
	goto_if_ne VAR_RESULT, 1, HelixLabItems_BagFull
	setvar VAR_0x8005, 2
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_EventScript_Ada::
	lock
	faceplayer
	special GetHelixLabItemsState
	goto_if_eq VAR_RESULT, 65535, HelixLabItems_Invalid
	goto_if_eq VAR_RESULT, 3, HelixLabItems_AdaResult
	goto_if_eq VAR_RESULT, 0, HelixLabItems_AdaBefore
	setvar VAR_0x8006, 2
	special CommitHelixLabItemsAction
	setvar VAR_0x8005, 4
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_Assay:
	setvar VAR_0x8005, 6
	call HelixLabItems_Say
	closemessage
	setvar VAR_0x8007, 1
	special ShowHelixLabItemsMenu
	waitstate
	goto_if_eq VAR_RESULT, 0, HelixLabItems_Shelter
	goto_if_eq VAR_RESULT, 1, HelixLabItems_Exposure
	goto HelixLabItems_Cancelled
HelixLabItems_Shelter:
	setvar VAR_0x8006, 3
	goto HelixLabItems_Condition
HelixLabItems_Exposure:
	setvar VAR_0x8006, 4
HelixLabItems_Condition:
	special CommitHelixLabItemsAction
	goto_if_ne VAR_RESULT, 1, HelixLabItems_Unavailable
	setvar VAR_0x8005, 22
	call HelixLabItems_Say
	closemessage
	setvar VAR_0x8007, 2
	special ShowHelixLabItemsMenu
	waitstate
	goto_if_eq VAR_RESULT, 0, HelixLabItems_Steady
	goto_if_eq VAR_RESULT, 1, HelixLabItems_Responsive
	goto HelixLabItems_Cancelled
HelixLabItems_Steady:
	setvar VAR_0x8006, 5
	goto HelixLabItems_Prediction
HelixLabItems_Responsive:
	setvar VAR_0x8006, 6
HelixLabItems_Prediction:
	special CommitHelixLabItemsAction
	goto_if_ne VAR_RESULT, 1, HelixLabItems_Unavailable
	setvar VAR_0x8005, 9
	special BufferHelixLabItemsText
	msgbox gStringVar4, MSGBOX_YESNO
	goto_if_ne VAR_RESULT, YES, HelixLabItems_Cancelled
	setvar VAR_0x8005, 10
	special BufferHelixLabItemsText
	message gStringVar4
	waitmessage
	special StartHelixLabSimulation
	goto_if_ne VAR_RESULT, 99, HelixLabItems_NoResult
	waitstate
	goto_if_ne VAR_RESULT, 1, HelixLabItems_NoResult
HelixLabItems_Result:
	setvar VAR_0x8005, 23
	call HelixLabItems_Say
	setvar VAR_0x8005, 24
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_AdaResult:
	setvar VAR_0x8005, 25
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_AdaBefore:
	setvar VAR_0x8005, 21
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_NeedGuide:
	setvar VAR_0x8005, 1
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_NeedResident:
	setvar VAR_0x8005, 5
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_BagFull:
	setvar VAR_0x8005, 3
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_Unavailable:
	setvar VAR_0x8005, 13
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_NoResult:
	setvar VAR_0x8005, 11
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_Invalid:
	setvar VAR_0x8005, 18
	call HelixLabItems_Say
	goto HelixLabItems_End
HelixLabItems_Cancelled:
	setvar VAR_0x8005, 12
	call HelixLabItems_Say
HelixLabItems_End:
	special ClearHelixLabItemsPreview
	closemessage
	releaseall
	end
HelixLabItems_Say:
	special BufferHelixLabItemsText
	msgbox gStringVar4, MSGBOX_DEFAULT
	return
