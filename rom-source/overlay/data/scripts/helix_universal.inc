@ Read-only native record desk. Advanced values are deliberately optional.
HelixUniversal_EventScript_Inspect::
	lock
	faceplayer
	special HelixUniversalInspectFirst
	goto_if_eq VAR_0x8004, 1, HelixUniversal_PT
	goto_if_ne VAR_RESULT, 1, HelixUniversal_UnavailableEN
	goto_if_eq VAR_0x8005, 2, HelixUniversal_LegacyEN
	msgbox HelixUniversal_EncounterEN, MSGBOX_DEFAULT
	goto HelixUniversal_DetailsEN
HelixUniversal_LegacyEN:
	msgbox HelixUniversal_LegacyTextEN, MSGBOX_DEFAULT
HelixUniversal_DetailsEN:
	msgbox HelixUniversal_QuestionEN, MSGBOX_YESNO
	goto_if_ne VAR_RESULT, YES, HelixUniversal_End
	msgbox HelixUniversal_CodesEN, MSGBOX_DEFAULT
	goto HelixUniversal_End
HelixUniversal_UnavailableEN:
	msgbox HelixUniversal_MissingEN, MSGBOX_DEFAULT
	goto HelixUniversal_End
HelixUniversal_PT:
	goto_if_ne VAR_RESULT, 1, HelixUniversal_UnavailablePT
	goto_if_eq VAR_0x8005, 2, HelixUniversal_LegacyPT
	msgbox HelixUniversal_EncounterPT, MSGBOX_DEFAULT
	goto HelixUniversal_DetailsPT
HelixUniversal_LegacyPT:
	msgbox HelixUniversal_LegacyTextPT, MSGBOX_DEFAULT
HelixUniversal_DetailsPT:
	msgbox HelixUniversal_QuestionPT, MSGBOX_YESNO
	goto_if_ne VAR_RESULT, YES, HelixUniversal_End
	msgbox HelixUniversal_CodesPT, MSGBOX_DEFAULT
	goto HelixUniversal_End
HelixUniversal_UnavailablePT:
	msgbox HelixUniversal_MissingPT, MSGBOX_DEFAULT
HelixUniversal_End:
	release
	end

HelixUniversal_LegacyTextEN:
	.string "{STR_VAR_1} has an older record.\nIts new DNA record keeps that past.\pIts parents are unknown.\nRegistration is not a birthday.$"
HelixUniversal_EncounterEN:
	.string "{STR_VAR_1} was registered\nat a wild encounter.\pIts parents are unknown.\nCapture keeps that same individual.$"
HelixUniversal_QuestionEN:
	.string "PC storage and evolution keep\nits identity and inherited DNA.\pOpen the advanced record?$"
HelixUniversal_CodesEN:
	.string "Local number: {STR_VAR_2}\nDNA check: {STR_VAR_3}\pThis fictional DNA is not its IVs.\nTraining does not rewrite it.$"
HelixUniversal_MissingEN:
	.string "This first study covers WINGULL\nand PELIPPER in your party or PC.\pNo readable record was found.\nYour POKéMON are unchanged.$"
HelixUniversal_LegacyTextPT:
	.string "{STR_VAR_1} tem um registro antigo.\nO novo DNA preserva seu passado.\pSeus pais sao desconhecidos.\nRegistro nao é nascimento.$"
HelixUniversal_EncounterPT:
	.string "{STR_VAR_1} recebeu um registro\nno encontro selvagem.\pSeus pais sao desconhecidos.\nA captura mantém o indivíduo.$"
HelixUniversal_QuestionPT:
	.string "PC e evoluçao mantêm a identidade\ne o DNA herdável.\pAbrir o registro avançado?$"
HelixUniversal_CodesPT:
	.string "Número local: {STR_VAR_2}\nResumo DNA: {STR_VAR_3}\pEste DNA fictício nao sao os IVs.\nTreinar nao o reescreve.$"
HelixUniversal_MissingPT:
	.string "Este estudo inclui WINGULL\ne PELIPPER na equipe ou no PC.\pNenhum registro legível encontrado.\nSeus POKéMON seguem iguais.$"
