# Local recipe: run makepkg -si from the cloned repository root.
# Spark and its icon are downloaded/extracted later, never packaged here.
pkgname=spark-omarchy
pkgver=0.1.0
pkgrel=1
pkgdesc='Unofficial experimental Spark Mail integration for Omarchy using Wine'
arch=('x86_64')
url='https://github.com/JustinBeaudry/spark-omarchy'
license=('MIT')
depends=('wine' '7zip' 'python' 'curl' 'desktop-file-utils')
makedepends=('clang' 'binutils')
source=()
sha256sums=()

build() {
  cd "$startdir"
  bash bin/build-shim "$srcdir/generated-native"
}

check() {
  cd "$startdir"
  bash bin/test
}

package() {
  local target="$pkgdir/usr/lib/$pkgname"
  install -d "$target/bin" "$target/native" "$pkgdir/usr/bin"
  cp -r "$startdir/spark_omarchy" "$target/"
  find "$target" -type d -name __pycache__ -prune -exec rm -rf '{}' +
  install -m644 "$startdir/manifest.json" "$target/manifest.json"
  install -m755 "$startdir/bin/spark-omarchy" "$target/bin/spark-omarchy"
  install -m644 "$srcdir/generated-native/spkenv.dll" "$target/native/spkenv.dll"
  ln -s /usr/lib/spark-omarchy/bin/spark-omarchy "$pkgdir/usr/bin/spark-omarchy"
  install -Dm644 "$startdir/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 "$startdir/README.md" "$pkgdir/usr/share/doc/$pkgname/README.md"
  cp -r "$startdir/docs" "$pkgdir/usr/share/doc/$pkgname/"
}
