import Foundation

enum WakeLanguage: String, CaseIterable {
    case english = "en"
    case simplifiedChinese = "zh-Hans"

    static let preferenceKey = "wakeLanguage"
    static var current: Self {
        Self(rawValue: UserDefaults.standard.string(forKey: preferenceKey) ?? "") ?? .english
    }
    var locale: Locale { Locale(identifier: rawValue) }
    var title: String {
        switch self {
        case .english: return "English"
        case .simplifiedChinese: return "简体中文"
        }
    }
}

private let chineseBundle = Bundle.main.path(forResource: "zh-Hans", ofType: "lproj")
    .flatMap { Bundle(path: $0) }

// English is the source language. Pass user text as a format argument, never as a key.
func l(_ english: String, _ values: CVarArg..., language: WakeLanguage = .current) -> String {
    let format = language == .simplifiedChinese
        ? chineseBundle?.localizedString(forKey: english, value: english, table: nil) ?? english : english
    return values.isEmpty ? format : String(format: format, locale: language.locale, arguments: values)
}

func wakeList(_ values: [String]) -> String {
    values.joined(separator: WakeLanguage.current == .simplifiedChinese ? "、" : ", ")
}
