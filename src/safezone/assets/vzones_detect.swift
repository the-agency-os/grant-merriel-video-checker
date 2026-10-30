import Foundation
import Vision
import CoreGraphics
import ImageIO

func emit(_ obj: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: obj)
    print(String(data: data, encoding: .utf8)!)
    fflush(stdout)
}

func px(_ r: CGRect, _ w: Int, _ h: Int) -> [Int] {
    let x0 = Int((r.minX * CGFloat(w)).rounded()), x1 = Int((r.maxX * CGFloat(w)).rounded())
    let y0 = Int(((1 - r.maxY) * CGFloat(h)).rounded()), y1 = Int(((1 - r.minY) * CGFloat(h)).rounded())
    return [x0, y0, x1, y1]
}

while let line = readLine() {
    let path = line.trimmingCharacters(in: .whitespacesAndNewlines)
    if path.isEmpty { continue }
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        emit(["path": path, "error": "unreadable"]); continue
    }
    let w = img.width, h = img.height
    let textReq = VNRecognizeTextRequest()
    textReq.recognitionLevel = .accurate
    textReq.usesLanguageCorrection = true
    textReq.recognitionLanguages = ["en-US", "es-ES", "pt-BR"]
    if #available(macOS 13.0, *) { textReq.automaticallyDetectsLanguage = false }
    let faceReq = VNDetectFaceRectanglesRequest()
    do {
        try VNImageRequestHandler(cgImage: img, options: [:]).perform([textReq, faceReq])
    } catch {
        emit(["path": path, "error": "vision: \(error.localizedDescription)"]); continue
    }
    var texts: [[String: Any]] = []
    for o in textReq.results ?? [] {
        guard let c = o.topCandidates(1).first else { continue }
        texts.append(["s": c.string, "c": Double(c.confidence), "box": px(o.boundingBox, w, h)])
    }
    let faces = (faceReq.results ?? []).map { px($0.boundingBox, w, h) }
    emit(["path": path, "w": w, "h": h, "text": texts, "faces": faces])
}
