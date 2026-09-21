param([ValidateSet('list', 'request')][string]$Action = 'list')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
    if ($Action -eq 'list') {
        $items = @(foreach ($store in @('CurrentUser', 'LocalMachine')) {
            Get-ChildItem -LiteralPath "Cert:\$store\My" | Where-Object { $_.HasPrivateKey } | ForEach-Object {
                [PSCustomObject]@{
                    store = $store
                    thumbprint = $_.Thumbprint
                    der = [Convert]::ToBase64String($_.RawData)
                }
            }
        })
        ConvertTo-Json -InputObject $items -Compress
    } else {
        $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
        if ($payload.store -notin @('CurrentUser', 'LocalMachine') -or $payload.thumbprint -notmatch '^[A-Fa-f0-9]{40}$') {
            throw 'Certificado inválido.'
        }
        if ($payload.url -notmatch '^https://(h)?nfce\.fazenda\.mg\.gov\.br/nfce/services/NFe(StatusServico|ConsultaProtocolo)4$') {
            throw 'Endpoint não permitido.'
        }
        $cert = Get-Item -LiteralPath "Cert:\$($payload.store)\My\$($payload.thumbprint)"
        if (-not $cert.HasPrivateKey -or $cert.NotAfter -lt (Get-Date) -or $cert.NotBefore -gt (Get-Date)) {
            throw 'Certificado sem chave privada ou fora da validade.'
        }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $service = ($payload.url -split '/')[-1]
        $method = if ($service -eq 'NFeStatusServico4') { 'nfeStatusServicoNF' } else { 'nfeConsultaNF' }
        $soapAction = "http://www.portalfiscal.inf.br/nfe/wsdl/$service/$method"
        $contentType = 'application/soap+xml; charset=utf-8; action="{0}"' -f $soapAction
        $response = Invoke-WebRequest -UseBasicParsing -Uri $payload.url -Method Post -Certificate $cert `
            -ContentType $contentType -Body ([Text.Encoding]::UTF8.GetBytes($payload.xml)) `
            -TimeoutSec 45 -MaximumRedirection 0
        [Console]::Write([string]$response.Content)
    }
} catch {
    # Não devolver corpo remoto, PIN ou detalhes da chave nos logs.
    [Console]::Error.Write('Falha no acesso ao certificado ou à SEFAZ. Verifique validade, driver/PIN, rede e cadeia ICP-Brasil.')
    exit 1
}

