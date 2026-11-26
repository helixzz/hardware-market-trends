#!/bin/bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
fetch() { id="$1"; url="$2"; curl -L --silent --show-error --max-time 30 -A "$UA" "$url" -o "cdw-$id.html" 2>>curl-errors.log; }
fetch 7085698 "https://www.cdw.com/product/micron-7450-pro-ssd-7.68-tb-u.3-pcie-4.0-nvme/7085698" &
fetch 7467127 "https://www.cdw.com/product/micron-6500-ion-ssd-enterprise-30.72-tb-u.3-pcie-4.0-x4-nvme-ta/7467127" &
fetch 7741004 "https://www.cdw.com/product/solidigm-d5-p5336-15.36tb-2.5-pcie-solid-state-drive/7741004" &
fetch 7785180 "https://www.cdw.com/product/solidigm-d5-p5336-30.72-tb-solid-state-drive-2.5-internal-u.2-pci-exp/7785180" &
fetch 7785193 "https://www.cdw.com/product/solidigm-d5-p5336-61.44-tb-solid-state-drive-2.5-internal-u.2-pci-exp/7785193" &
fetch 7825825 "https://www.cdw.com/product/micron-ddr5-module-64-gb-dimm-288-pin-5600-mhz-pc5-44800-regi/7825825" &
fetch 7946438 "https://www.cdw.com/product/micron-ddr5-module-128-gb-dimm-288-pin-5600-mhz-pc5-44800-reg/7946438" &
fetch 8194577 "https://www.cdw.com/product/samsung-ddr5-module-96-gb-dimm-288-pin-2800-mhz-pc5-44800-reg/8194577" &
fetch 8215730 "https://www.cdw.com/product/micron-9550-pro-ssd-read-intensive-15.36-tb-pci-express-5.0-x4-nvm/8215730" &
fetch 8215732 "https://www.cdw.com/product/micron-9550-pro-ssd-enterprise-read-intensive-3.84-tb-pci-express/8215732" &
fetch 8215733 "https://www.cdw.com/product/micron-9550-pro-ssd-read-intensive-enterprise-30.72-tb-u.2-pcie-5.0/8215733" &
fetch 8439578 "https://www.cdw.com/product/micron-128gb-ddr5-6400-ecc-rdimm/8439578" &
fetch 8455168 "https://www.cdw.com/product/solidigm-d5-p5336-122.88-tb-solid-state-drive-2.5-internal-u.2-pci-ex/8455168" &
fetch 8458582 "https://www.cdw.com/product/samsung-ddr5-module-96-gb-dimm-288-pin-6400-mhz-pc5-51200-reg/8458582" &
fetch 8505971 "https://www.cdw.com/product/micron-ddr5-module-32-gb-dimm-288-pin-6400-mhz-pc5-51200-regi/8505971" &
wait
echo done
