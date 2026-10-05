/** @odoo-module **/

/**
 * Telefondan çekilen fotoğrafı yüklemeden önce küçült (uzun kenar en fazla 1280px, JPEG).
 * 4–5 MB'lık telefon fotoğrafı ~200 KB'a iner; sunucu da en fazla 1280px saklar.
 */
export function readPhoto(file, maxEdge = 1280, quality = 0.82) {
    return new Promise((resolve, reject) => {
        if (!file) {
            resolve("");
            return;
        }
        const url = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => {
            const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
            const canvas = document.createElement("canvas");
            canvas.width = Math.round(img.width * scale);
            canvas.height = Math.round(img.height * scale);
            canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
            URL.revokeObjectURL(url);
            resolve(canvas.toDataURL("image/jpeg", quality));
        };
        img.onerror = (e) => {
            URL.revokeObjectURL(url);
            reject(e);
        };
        img.src = url;
    });
}
