import Foundation

enum AgentState: String {
    case ready = "San sang"
    case openingTikTok = "Dang mo TikTok"
    case waitingForScreenshot = "Cho screenshot"
    case checkingLoad = "Dang kiem tra load"
    case loaded = "Load thanh cong"
    case detectingObject = "Dang tim hop qua"
    case objectFound = "Da tim thay hop qua"
    case objectNotFound = "Khong tim thay hop qua"
    case loadTimeout = "Load timeout"
    case failed = "Co loi"
}

